using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Troika.Desktop;

static class VoiceIdentityTests {
    private static int passed;
    private static void Assert(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static double[] Vector(int index) { var value = new double[128]; value[index] = 1; return value; }
    private static VoiceSignature Signature(int index) { return new VoiceSignature(Vector(index), 450); }
    private static void Throws<T>(Action action) where T : Exception { try { action(); } catch (T) { return; } throw new Exception("Expected " + typeof(T).Name); }
    private static async Task ThrowsAsync<T>(Func<Task> action) where T : Exception { try { await action(); } catch (T) { return; } throw new Exception("Expected " + typeof(T).Name); }
    private static async Task Test(string name, Func<Task> action) { await action(); passed++; Console.WriteLine("PASS " + name); }
    private sealed class FakeExtractor : IVoiceSignatureExtractor {
        public int Calls;
        public Action During;
        public VoiceSignature Value = Signature(0);
        public VoiceSignature Extract(byte[] wav, CancellationToken cancellation) { Calls++; cancellation.ThrowIfCancellationRequested(); if (During != null) During(); cancellation.ThrowIfCancellationRequested(); return Value; }
    }
    private static void Enroll(VoiceIdentityStore store, string owner) { store.Enroll(owner, new[] { Signature(0), Signature(0), Signature(0) }); }
    private static async Task Run() {
        string root = Path.Combine(Path.GetTempPath(), "TroikaVoiceIdentityTests-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        try {
            const string owner = "owner@example.test";
            var store = new VoiceIdentityStore(root);
            await Test("invalid vectors and short speech fail closed", () => {
                Throws<InvalidDataException>(() => new VoiceSignature(new double[128], 450));
                Throws<InvalidDataException>(() => new VoiceSignature(new double[127], 450));
                var nan = Vector(0); nan[1] = double.NaN; Throws<InvalidDataException>(() => new VoiceSignature(nan, 450));
                var infinity = Vector(0); infinity[1] = double.PositiveInfinity; Throws<InvalidDataException>(() => new VoiceSignature(infinity, 450));
                Throws<InvalidDataException>(() => new VoiceSignature(Vector(0), 399));
                Assert(new VoiceSignature(Vector(0), 400).Frames == 400, "four-second boundary rejected"); return Task.FromResult(0);
            });
            await Test("enrollment requires three consistent samples", () => {
                Throws<InvalidDataException>(() => store.Enroll(owner, new[] { Signature(0), Signature(0) }));
                Throws<InvalidDataException>(() => store.Enroll(owner, new[] { Signature(0), Signature(0), Signature(1) }));
                Assert(!store.Load(owner).Exists, "partial enrollment persisted"); return Task.FromResult(0);
            });
            await Test("enrollment stays disabled until explicit opt in", () => {
                Enroll(store, owner); var profile = store.Load(owner);
                Assert(profile.Exists && !profile.Enabled && !profile.Damaged && profile.Samples.Length == 3, "profile not disabled/valid");
                Assert(!Encoding.UTF8.GetString(File.ReadAllBytes(store.ProfilePath(owner))).Contains("samples"), "embeddings persisted without DPAPI");
                return Task.FromResult(0);
            });
            await Test("account-scoped encrypted profile reload", () => {
                Assert(!store.Load("other@example.test").Exists, "profile leaked across accounts");
                Assert(store.Load("OWNER@example.test").Exists, "email canonicalization lost profile");
                var reopened = new VoiceIdentityStore(root); Assert(reopened.Load(owner).Samples[0][0] > 0.99, "encrypted profile did not reload");
                File.Copy(store.ProfilePath(owner), store.ProfilePath("other@example.test"));
                Assert(store.Load("other@example.test").Damaged, "owner binding not enforced"); store.Delete("other@example.test"); return Task.FromResult(0);
            });
            await Test("disabled mode preserves ordinary voice without model work", async () => {
                var fake = new FakeExtractor(); var gate = new VoiceRequestGate(store, fake); int stt = 0;
                string result = await gate.Transcribe(new byte[0], owner, () => true, (wav, token) => { stt++; return Task.FromResult("accepted"); }, CancellationToken.None);
                Assert(result == "accepted" && stt == 1 && fake.Calls == 0, "disabled mode changed");
            });
            await Test("known speaker passes local verification before STT", async () => {
                store.SetEnabled(owner, true); var fake = new FakeExtractor(); var gate = new VoiceRequestGate(store, fake); int stt = 0;
                string result = await gate.Transcribe(new byte[0], owner, () => true, (wav, token) => { Assert(fake.Calls == 1, "STT preceded local check"); stt++; return Task.FromResult("accepted"); }, CancellationToken.None);
                Assert(result == "accepted" && stt == 1, "known speaker rejected");
            });
            await Test("different speaker never reaches STT", async () => {
                var fake = new FakeExtractor { Value = Signature(1) }; var gate = new VoiceRequestGate(store, fake); int stt = 0;
                await ThrowsAsync<InvalidDataException>(async () => { await gate.Transcribe(new byte[0], owner, () => true, (wav, token) => { stt++; return Task.FromResult("bad"); }, CancellationToken.None); });
                Assert(stt == 0, "different speaker reached network");
            });
            await Test("account change during extraction cancels STT", async () => {
                bool current = true; var fake = new FakeExtractor { During = () => current = false }; var gate = new VoiceRequestGate(store, fake); int stt = 0;
                await ThrowsAsync<OperationCanceledException>(async () => { await gate.Transcribe(new byte[0], owner, () => current, (wav, token) => { stt++; return Task.FromResult("bad"); }, CancellationToken.None); });
                Assert(stt == 0, "stale owner reached STT");
            });
            await Test("profile change during extraction cancels STT", async () => {
                var fake = new FakeExtractor { During = () => store.SetEnabled(owner, false) }; var gate = new VoiceRequestGate(store, fake); int stt = 0;
                await ThrowsAsync<OperationCanceledException>(async () => { await gate.Transcribe(new byte[0], owner, () => true, (wav, token) => { stt++; return Task.FromResult("bad"); }, CancellationToken.None); });
                Assert(stt == 0, "changed consent reached STT"); store.SetEnabled(owner, true);
            });
            await Test("stop during extraction cancels STT", async () => {
                using (var stop = new CancellationTokenSource()) {
                    var fake = new FakeExtractor { During = stop.Cancel }; var gate = new VoiceRequestGate(store, fake); int stt = 0;
                    await ThrowsAsync<OperationCanceledException>(async () => { await gate.Transcribe(new byte[0], owner, () => true, (wav, token) => { stt++; return Task.FromResult("bad"); }, stop.Token); });
                    Assert(stt == 0, "stopped request reached STT");
                }
            });
            await Test("stale transcription cannot update another account", async () => {
                bool current = true; var gate = new VoiceRequestGate(store, new FakeExtractor());
                await ThrowsAsync<OperationCanceledException>(async () => { await gate.Transcribe(new byte[0], owner, () => current, (wav, token) => { current = false; return Task.FromResult("must not display"); }, CancellationToken.None); });
            });
            await Test("corrupted enabled profile blocks STT until deletion", async () => {
                File.WriteAllBytes(store.ProfilePath(owner), new byte[] { 1, 2, 3 }); var profile = store.Load(owner); Assert(profile.Damaged && profile.Enabled, "corruption disabled check");
                var gate = new VoiceRequestGate(store, new FakeExtractor()); int stt = 0;
                await ThrowsAsync<InvalidDataException>(async () => { await gate.Transcribe(new byte[0], owner, () => true, (wav, token) => { stt++; return Task.FromResult("bad"); }, CancellationToken.None); });
                Assert(stt == 0, "corrupt profile reached STT"); store.Delete(owner); Assert(!store.Load(owner).Exists && !store.Load(owner).Enabled, "deletion kept voice restriction");
            });
            await Test("median comparison tolerates one lower enrollment similarity", () => {
                double[] near = Vector(0); near[1] = .25;
                Assert(VoiceSignature.Matches(new[] { Vector(0), near, Vector(1) }, Signature(0)), "median consensus failed");
                Assert(!VoiceSignature.Matches(new[] { Vector(0), Vector(1), Vector(1) }, Signature(0)), "single sample bypassed consensus"); return Task.FromResult(0);
            });
            await Test("WAV parsing rejects malformed and wrong formats", () => {
                int start, length; byte[] wav = VoiceRecorder.Wav(new byte[160000]); VoskVoiceSignatureExtractor.PcmRange(wav, out start, out length); Assert(start == 44 && length == 160000, "PCM range incorrect");
                wav[24] = 0; Throws<InvalidDataException>(() => VoskVoiceSignatureExtractor.PcmRange(wav, out start, out length));
                Throws<InvalidDataException>(() => VoskVoiceSignatureExtractor.PcmRange(new byte[44], out start, out length)); return Task.FromResult(0);
            });
            await Test("missing local model fails closed", () => {
                using (var native = new VoskVoiceSignatureExtractor(Path.Combine(root, "missing-model"))) Throws<InvalidDataException>(() => native.Extract(VoiceRecorder.Wav(new byte[160000]), CancellationToken.None));
                return Task.FromResult(0);
            });
            Console.WriteLine("Voice identity: " + passed + " passed.");
        } finally { Directory.Delete(root, true); }
    }
    private static void NativeSmoke(string fixture) {
        byte[] wav = File.ReadAllBytes(fixture);
        try {
            using (var native = new VoskVoiceSignatureExtractor(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "voice-id"))) {
                var timer = Stopwatch.StartNew(); VoiceSignature first = native.Extract(wav, CancellationToken.None); timer.Stop(); long cold = timer.ElapsedMilliseconds;
                timer.Restart(); VoiceSignature second = native.Extract(wav, CancellationToken.None); timer.Stop();
                Assert(first.Vector.Length == 128 && first.Frames >= 400 && VoiceSignature.Similarity(first.Vector, second.Vector) > 0.99, "native speaker extraction failed");
                Console.WriteLine("Native fixture: dimensions=128 frames=" + first.Frames + " cold_ms=" + cold + " warm_ms=" + timer.ElapsedMilliseconds + " similarity=" + VoiceSignature.Similarity(first.Vector, second.Vector).ToString("F6", System.Globalization.CultureInfo.InvariantCulture));
            }
        } finally { Array.Clear(wav, 0, wav.Length); }
    }
    public static int Main(string[] arguments) { try { if (arguments.Length == 2 && arguments[0] == "--native") NativeSmoke(arguments[1]); else Run().GetAwaiter().GetResult(); return 0; } catch (Exception error) { Console.Error.WriteLine(error); return 1; } }
}
