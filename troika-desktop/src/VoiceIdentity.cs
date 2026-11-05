using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed class VoiceSignature {
        public const int Dimensions = 128;
        public const int MinimumFrames = 400;
        public const double MinimumSimilarity = 0.75;
        public readonly double[] Vector;
        public readonly int Frames;
        public VoiceSignature(double[] vector, int frames) {
            if (frames < MinimumFrames || frames > 6000) throw new InvalidDataException("Недостаточно речи. Повторите фразу длиной 5–8 секунд.");
            Vector = Normalize(vector); Frames = frames;
        }
        public static double[] Normalize(double[] value) {
            if (value == null || value.Length != Dimensions || value.Any(x => double.IsNaN(x) || double.IsInfinity(x) || Math.Abs(x) > 1000000)) throw new InvalidDataException("Не удалось получить образец голоса. Повторите запись.");
            double norm = Math.Sqrt(value.Sum(x => x * x));
            if (norm < 0.000001 || double.IsInfinity(norm)) throw new InvalidDataException("В записи недостаточно речи. Повторите запись.");
            return value.Select(x => x / norm).ToArray();
        }
        public static double Similarity(double[] left, double[] right) {
            var a = Normalize(left); var b = Normalize(right);
            return a.Zip(b, (x, y) => x * y).Sum();
        }
        public static bool Consistent(IEnumerable<VoiceSignature> samples, VoiceSignature candidate) { return samples.All(sample => Similarity(sample.Vector, candidate.Vector) >= MinimumSimilarity); }
        public static bool Matches(double[][] samples, VoiceSignature candidate) {
            if (samples == null || samples.Length != 3) return false;
            var scores = samples.Select(sample => Similarity(sample, candidate.Vector)).OrderBy(x => x).ToArray();
            return scores[1] >= MinimumSimilarity;
        }
    }

    public sealed class VoiceIdentityProfile {
        public bool Exists, Enabled, Damaged;
        public string Revision = "";
        public double[][] Samples;
    }

    // Only model embeddings are persisted. Raw microphone audio never enters this store.
    public sealed class VoiceIdentityStore {
        public const string ModelVersion = "vosk-model-spk-0.4";
        private readonly string root;
        public VoiceIdentityStore(string directory) { root = Path.Combine(Path.GetFullPath(directory), "voice-identity"); }
        private static string OwnerHash(string owner) {
            if (string.IsNullOrWhiteSpace(owner)) throw new InvalidOperationException("Для регистрации голоса войдите в аккаунт.");
            return LocalStore.Hash(Encoding.UTF8.GetBytes(owner.Trim().ToLowerInvariant()));
        }
        public string ProfilePath(string owner) { return Path.Combine(root, OwnerHash(owner) + ".dat"); }
        public VoiceIdentityProfile Load(string owner) {
            string path = ProfilePath(owner);
            if (!File.Exists(path)) return new VoiceIdentityProfile();
            byte[] plain = null;
            try {
                if (new FileInfo(path).Length > 64000) throw new InvalidDataException();
                plain = ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.CurrentUser);
                var value = Json.Parse(Encoding.UTF8.GetString(plain));
                if (Json.Text(value, "model") != ModelVersion || Json.Text(value, "owner") != OwnerHash(owner) || Json.Number(value, "schema") != 1 || Json.Text(value, "revision").Length != 32) throw new InvalidDataException();
                var raw = Json.Get(value, "samples") as object[];
                if (raw == null || raw.Length != 3 || !(Json.Get(value, "enabled") is bool)) throw new InvalidDataException();
                var samples = raw.Select(ReadVector).ToArray();
                for (int i = 0; i < samples.Length; i++) for (int j = 0; j < i; j++) if (VoiceSignature.Similarity(samples[i], samples[j]) < VoiceSignature.MinimumSimilarity) throw new InvalidDataException();
                return new VoiceIdentityProfile { Exists = true, Enabled = Json.Flag(value, "enabled"), Revision = Json.Text(value, "revision"), Samples = samples };
            } catch { return new VoiceIdentityProfile { Exists = true, Enabled = true, Damaged = true }; }
            finally { if (plain != null) Array.Clear(plain, 0, plain.Length); }
        }
        private static double[] ReadVector(object raw) {
            var values = raw as IEnumerable;
            if (values == null || raw is string) throw new InvalidDataException();
            var result = new List<double>();
            foreach (var item in values) {
                if (!(item is double) && !(item is float) && !(item is int) && !(item is decimal)) throw new InvalidDataException();
                result.Add(Convert.ToDouble(item));
            }
            return VoiceSignature.Normalize(result.ToArray());
        }
        public void Enroll(string owner, IList<VoiceSignature> samples) {
            if (samples == null || samples.Count != 3) throw new InvalidDataException("Нужно записать три образца голоса.");
            for (int i = 0; i < samples.Count; i++) if (!VoiceSignature.Consistent(samples.Take(i), samples[i])) throw new InvalidDataException("Образцы голоса отличаются. Запишите их ещё раз в тихом месте.");
            Write(owner, samples.Select(x => x.Vector).ToArray(), false);
        }
        private void Write(string owner, double[][] samples, bool enabled) {
            byte[] plain = Encoding.UTF8.GetBytes(Json.Encode(new { schema = 1, owner = OwnerHash(owner), model = ModelVersion, revision = Guid.NewGuid().ToString("N"), enabled = enabled, samples = samples }));
            try { LocalStore.WriteAtomic(ProfilePath(owner), ProtectedData.Protect(plain, null, DataProtectionScope.CurrentUser)); }
            finally { Array.Clear(plain, 0, plain.Length); }
        }
        public void SetEnabled(string owner, bool enabled) {
            var profile = Load(owner);
            if (profile.Damaged || !profile.Exists) throw new InvalidDataException("Сначала зарегистрируйте голос. Повреждённый образец можно удалить и записать заново.");
            Write(owner, profile.Samples, enabled);
        }
        public void Delete(string owner) { string path = ProfilePath(owner); if (File.Exists(path)) File.Delete(path); }
    }

    public interface IVoiceSignatureExtractor { VoiceSignature Extract(byte[] wav, CancellationToken cancellation); }

    public sealed class VoiceRequestGate {
        private readonly VoiceIdentityStore store;
        private readonly IVoiceSignatureExtractor extractor;
        public VoiceRequestGate(VoiceIdentityStore profiles, IVoiceSignatureExtractor signatures) { store = profiles; extractor = signatures; }
        public async Task<string> Transcribe(byte[] wav, string owner, Func<bool> current, Func<byte[], CancellationToken, Task<string>> transcribe, CancellationToken cancellation) {
            cancellation.ThrowIfCancellationRequested(); if (!current()) throw new OperationCanceledException();
            var profile = store.Load(owner);
            if (profile.Enabled) {
                if (profile.Damaged || profile.Samples == null) throw new InvalidDataException("Образец недоступен. Зарегистрируйте голос заново в настройках «Мой голос».");
                var signature = await Task.Run(() => extractor.Extract(wav, cancellation), cancellation);
                cancellation.ThrowIfCancellationRequested(); if (!current()) throw new OperationCanceledException();
                var after = store.Load(owner);
                if (!after.Enabled || after.Damaged || after.Revision != profile.Revision) throw new OperationCanceledException();
                if (!VoiceSignature.Matches(profile.Samples, signature)) throw new InvalidDataException("Голос не совпал. Запрос не отправлен.");
            }
            cancellation.ThrowIfCancellationRequested(); if (!current()) throw new OperationCanceledException();
            string text = await transcribe(wav, cancellation);
            cancellation.ThrowIfCancellationRequested(); if (!current()) throw new OperationCanceledException();
            return text;
        }
    }

    public sealed class VoskVoiceSignatureExtractor : IVoiceSignatureExtractor, IDisposable {
        public const string ManifestSha256 = "3c587595b96d2cec42f228cb2828ddbf43c708b9ac7f84d19888dff5e5e5f12d";
        private readonly string assets;
        private readonly object sync = new object();
        private IntPtr model, speaker;
        private bool disposed;
        private static readonly object librarySync = new object();
        private static string loadedLibrary = "";
        private static readonly List<IntPtr> libraries = new List<IntPtr>();
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern void vosk_set_log_level(int level);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern IntPtr vosk_model_new(byte[] path);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern IntPtr vosk_spk_model_new(byte[] path);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern void vosk_model_free(IntPtr value);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern void vosk_spk_model_free(IntPtr value);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern IntPtr vosk_recognizer_new_spk(IntPtr model, float rate, IntPtr speaker);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern int vosk_recognizer_accept_waveform(IntPtr recognizer, byte[] data, int length);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern IntPtr vosk_recognizer_final_result(IntPtr recognizer);
        [DllImport("libvosk.dll", CallingConvention = CallingConvention.Cdecl)] private static extern void vosk_recognizer_free(IntPtr recognizer);
        public VoskVoiceSignatureExtractor(string directory) { assets = Path.GetFullPath(directory); }
        public bool Available { get { return File.Exists(Path.Combine(assets, "manifest.json")) && File.Exists(Path.Combine(assets, "native", "libvosk.dll")); } }
        private static byte[] Utf8Path(string value) { return Encoding.UTF8.GetBytes(value + "\0"); }
        private void Initialize(CancellationToken cancellation) {
            if (disposed) throw new ObjectDisposedException("VoskVoiceSignatureExtractor");
            if (model != IntPtr.Zero && speaker != IntPtr.Zero) return;
            try {
                VerifyAssets(cancellation);
                string native = Path.Combine(assets, "native");
                lock (librarySync) {
                    if (loadedLibrary.Length > 0 && loadedLibrary != native) throw new InvalidDataException("В процессе уже загружена другая голосовая модель.");
                    if (loadedLibrary.Length == 0) {
                        foreach (string name in new[] { "libwinpthread-1.dll", "libgcc_s_seh-1.dll", "libstdc++-6.dll", "libvosk.dll" }) {
                            IntPtr library = LoadLibraryEx(Path.Combine(native, name), IntPtr.Zero, 0x8);
                            if (library == IntPtr.Zero) throw new InvalidDataException("Не удалось загрузить локальную модель голоса. Переустановите приложение.");
                            libraries.Add(library);
                        }
                        loadedLibrary = native;
                    }
                }
                vosk_set_log_level(-1);
                cancellation.ThrowIfCancellationRequested();
                model = vosk_model_new(Utf8Path(Path.Combine(assets, "vosk-model-small-ru-0.22")));
                if (model == IntPtr.Zero) throw new InvalidDataException("Локальная модель речи недоступна. Переустановите приложение.");
                cancellation.ThrowIfCancellationRequested();
                speaker = vosk_spk_model_new(Utf8Path(Path.Combine(assets, VoiceIdentityStore.ModelVersion)));
                if (speaker == IntPtr.Zero) throw new InvalidDataException("Локальная модель голоса недоступна. Переустановите приложение.");
            } catch { FreeModels(); throw; }
        }
        private void VerifyAssets(CancellationToken cancellation) {
            string marker = Path.Combine(assets, "manifest.json");
            if (!File.Exists(marker) || new FileInfo(marker).Length > 64000 || LocalStore.Hash(File.ReadAllBytes(marker)) != ManifestSha256) throw new InvalidDataException("Локальная модель голоса отсутствует или повреждена. Переустановите приложение.");
            foreach (var item in Json.Rows(Json.Parse(File.ReadAllText(marker)), "files")) {
                cancellation.ThrowIfCancellationRequested(); string relative = Json.Text(item, "path");
                string path = Path.GetFullPath(Path.Combine(assets, relative.Replace('/', Path.DirectorySeparatorChar)));
                if (!path.StartsWith(assets + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || !File.Exists(path) || new FileInfo(path).Length != Json.Number(item, "size")) throw new InvalidDataException("Файлы локальной модели голоса повреждены. Переустановите приложение.");
                using (var stream = File.OpenRead(path)) using (var sha = SHA256.Create()) if (BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant() != Json.Text(item, "sha256")) throw new InvalidDataException("Файлы локальной модели голоса повреждены. Переустановите приложение.");
            }
        }
        public VoiceSignature Extract(byte[] wav, CancellationToken cancellation) {
            int start, length; PcmRange(wav, out start, out length);
            if (length < 16000 * 2 * 4) throw new InvalidDataException("Недостаточно речи. Повторите фразу длиной 5–8 секунд.");
            lock (sync) {
                cancellation.ThrowIfCancellationRequested(); Initialize(cancellation);
                IntPtr recognizer = vosk_recognizer_new_spk(model, 16000, speaker);
                if (recognizer == IntPtr.Zero) throw new InvalidDataException("Не удалось проверить голос на устройстве.");
                var chunk = new byte[6400];
                try {
                    // Keep one utterance: consuming Result after an endpoint would discard earlier speaker frames.
                    for (int offset = 0; offset < length; offset += chunk.Length) {
                        cancellation.ThrowIfCancellationRequested(); int count = Math.Min(chunk.Length, length - offset);
                        Buffer.BlockCopy(wav, start + offset, chunk, 0, count);
                        if (vosk_recognizer_accept_waveform(recognizer, chunk, count) < 0) throw new InvalidDataException("Не удалось обработать голос на устройстве.");
                    }
                    cancellation.ThrowIfCancellationRequested();
                    IntPtr pointer = vosk_recognizer_final_result(recognizer); int countBytes = 0;
                    if (pointer == IntPtr.Zero) throw new InvalidDataException("Не удалось получить образец голоса.");
                    while (Marshal.ReadByte(pointer, countBytes) != 0 && countBytes < 1024 * 1024) countBytes++;
                    if (countBytes >= 1024 * 1024) throw new InvalidDataException("Некорректный результат проверки голоса.");
                    var bytes = new byte[countBytes]; Marshal.Copy(pointer, bytes, 0, bytes.Length);
                    var result = Json.Parse(Encoding.UTF8.GetString(bytes)); Array.Clear(bytes, 0, bytes.Length);
                    var vector = Json.Get(result, "spk") as IEnumerable;
                    if (vector == null) throw new InvalidDataException("В записи недостаточно речи. Повторите фразу длиной 5–8 секунд.");
                    var values = new List<double>(); foreach (var value in vector) values.Add(Convert.ToDouble(value));
                    cancellation.ThrowIfCancellationRequested(); return new VoiceSignature(values.ToArray(), (int)Json.Number(result, "spk_frames"));
                } finally { Array.Clear(chunk, 0, chunk.Length); vosk_recognizer_free(recognizer); }
            }
        }
        public static void PcmRange(byte[] wav, out int start, out int length) {
            start = 0; length = 0;
            if (wav == null || wav.Length < 44 || wav.Length > 1920044 || Encoding.ASCII.GetString(wav, 0, 4) != "RIFF" || Encoding.ASCII.GetString(wav, 8, 4) != "WAVE") throw new InvalidDataException("Ожидается запись PCM WAV 16 кГц моно.");
            bool format = false;
            for (int at = 12; at <= wav.Length - 8;) {
                int size = BitConverter.ToInt32(wav, at + 4); if (size < 0 || size > wav.Length - at - 8) throw new InvalidDataException("Запись голоса повреждена.");
                string kind = Encoding.ASCII.GetString(wav, at, 4);
                if (kind == "fmt ") { if (size < 16 || BitConverter.ToInt16(wav, at + 8) != 1 || BitConverter.ToInt16(wav, at + 10) != 1 || BitConverter.ToInt32(wav, at + 12) != 16000 || BitConverter.ToInt16(wav, at + 22) != 16) throw new InvalidDataException("Ожидается запись PCM WAV 16 кГц моно."); format = true; }
                if (kind == "data") { if (!format || start != 0 || size % 2 != 0) throw new InvalidDataException("Запись голоса повреждена."); start = at + 8; length = size; }
                long next = (long)at + 8 + size + size % 2; if (next > wav.Length) throw new InvalidDataException("Запись голоса повреждена."); at = (int)next;
            }
            if (!format || start == 0 || length == 0) throw new InvalidDataException("В записи нет звука.");
        }
        private void FreeModels() { if (speaker != IntPtr.Zero) { vosk_spk_model_free(speaker); speaker = IntPtr.Zero; } if (model != IntPtr.Zero) { vosk_model_free(model); model = IntPtr.Zero; } }
        public void Dispose() { lock (sync) { disposed = true; FreeModels(); } }
    }
}
