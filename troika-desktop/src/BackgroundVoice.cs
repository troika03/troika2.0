using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Win32;

namespace Troika.Desktop {
    public sealed class WakeCommandAudio : IDisposable {
        // Audio starts after the wake cue, with a bounded wait for speech and
        // a silence endpoint. The wake utterance is never in this buffer.
        private const int SampleRate = 16000;
        private readonly MemoryStream pcm = new MemoryStream();
        private int skip = SampleRate * 4 / 10, waiting, quiet, loud;
        private int bufferedSilence;
        public bool Append(byte[] bytes, int count) {
            int ignored = Math.Min(skip, count / 2) * 2;
            skip -= ignored / 2;
            if (ignored == count) return true;
            double energy = 0;
            for (int i = ignored; i < count; i += 2) {
                var sample = (short)(bytes[i] | bytes[i + 1] << 8);
                energy += (double)sample * sample;
            }
            int samples = (count - ignored) / 2;
            if (energy / samples >= 220 * 220) {
                if (loud == 0 && bufferedSilence > 0) {
                    // Keep the real audio immediately preceding the first loud block.
                    pcm.Write(preroll, 0, bufferedSilence);
                }
                loud += samples;
                quiet = 0;
            } else if (loud == 0) {
                waiting += samples;
                bufferedSilence = Math.Min(count - ignored, preroll.Length);
                Buffer.BlockCopy(bytes, count - bufferedSilence, preroll, 0, bufferedSilence);
                return waiting < SampleRate * 5;
            } else quiet += samples;
            pcm.Write(bytes, ignored, count - ignored);
            return quiet < SampleRate * 11 / 10 && pcm.Length < SampleRate * 2 * 30;
        }
        private readonly byte[] preroll = new byte[3200];
        public byte[] Result() {
            if (loud < SampleRate / 5) return null;
            var bytes = pcm.ToArray();
            try { return VoiceRecorder.Wav(bytes); }
            finally { Array.Clear(bytes, 0, bytes.Length); }
        }
        public void Dispose() {
            Array.Clear(preroll, 0, preroll.Length);
            Array.Clear(pcm.GetBuffer(), 0, (int)pcm.Length);
            pcm.Dispose();
        }
    }

    public sealed partial class MainWindow {
        private readonly DispatcherTimer wakeTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(300) };
        private CancellationTokenSource wakeCancellation;
        private Task<byte[]> wakeWorker;
        private bool wakeEnabled, wakeReady, wakeRecording, wakeLocked, wakeSuspended;
        private string wakeError = "", wakeOwner = "";
        private DateTime wakeRetry;
        private int wakeTransition;
        private System.Windows.Controls.TextBlock wakeBadge;

        private void InitializeBackgroundVoice(bool enabled, string owner) {
            if (preview) return;
            wakeEnabled = enabled; wakeOwner = owner;
            SystemEvents.SessionSwitch += WakeSessionSwitch;
            SystemEvents.PowerModeChanged += WakePowerChanged;
            wakeTimer.Tick += delegate { ReconcileBackgroundVoice(); };
            wakeTimer.Start();
        }
        private void WakeSessionSwitch(object sender, SessionSwitchEventArgs e) {
            if (e.Reason == SessionSwitchReason.SessionLock || e.Reason == SessionSwitchReason.SessionUnlock)
                Dispatcher.BeginInvoke(new Action(() => { wakeLocked = e.Reason == SessionSwitchReason.SessionLock; ReconcileBackgroundVoice(); }));
        }
        private void WakePowerChanged(object sender, PowerModeChangedEventArgs e) {
            if (e.Mode == PowerModes.Suspend || e.Mode == PowerModes.Resume)
                Dispatcher.BeginInvoke(new Action(() => { wakeSuspended = e.Mode == PowerModes.Suspend; ReconcileBackgroundVoice(); }));
        }
        private bool WakeAvailable() {
            return WakeEnabledForAccount && !preview && !closed && !exitRequested && !wakeLocked && !wakeSuspended
                && !busy && !speaking && !recorder.Recording && !voiceEnrollment && !voiceProcessing
                && pendingApproval == null && projectSpeech == null && !codexConfirming && wakeTransition == 0;
        }
        private void ReconcileBackgroundVoice() {
            if (!WakeAvailable()) {
                CancelWakeCapture();
            } else if (wakeWorker == null && DateTime.UtcNow >= wakeRetry) {
                var cancellation = new CancellationTokenSource();
                wakeCancellation = cancellation;
                var owner = api.Account.Email;
                var capture = Task.Run(() => CaptureWakeCommand(cancellation));
                wakeWorker = capture;
                var pending = CompleteWakeCapture(capture, cancellation, owner);
            }
            RefreshWakeIndicator();
        }
        private byte[] CaptureWakeCommand(CancellationTokenSource cancellation) {
            using (var audio = new WakeCommandAudio()) {
                bool triggered = false;
                voiceSignatures.ListenForWake(recognize => VoiceRecorder.Listen((bytes, count) => {
                    if (triggered) return audio.Append(bytes, count);
                    if (!recognize(bytes, count)) return true;
                    triggered = true;
                    DispatchWakeState(cancellation, true);
                    return true;
                }, () => DispatchWakeState(cancellation, false), cancellation.Token), cancellation.Token);
                cancellation.Token.ThrowIfCancellationRequested();
                return triggered ? audio.Result() : null;
            }
        }
        private void DispatchWakeState(CancellationTokenSource cancellation, bool recording) {
            Dispatcher.BeginInvoke(new Action(() => {
                if (wakeCancellation != cancellation || cancellation.IsCancellationRequested || !WakeAvailable()) return;
                wakeReady = true;
                wakeRecording = recording;
                wakeError = "";
                if (recording) {
                    System.Media.SystemSounds.Asterisk.Play();
                    orb.SetState("listening");
                    SetStatus("Слушаю команду…", false);
                }
                RefreshWakeIndicator();
            }));
        }
        private async Task CompleteWakeCapture(Task<byte[]> capture, CancellationTokenSource cancellation, string owner) {
            byte[] audio = null;
            try { audio = await capture; }
            catch (OperationCanceledException) { }
            catch (Exception error) {
                wakeError = error is InvalidOperationException || error is IOException
                    ? error.Message : "Фоновый микрофон недоступен. Переустановите Тройку или проверьте микрофон.";
                wakeRetry = DateTime.UtcNow.AddSeconds(15);
            }
            bool forward = audio != null && !cancellation.IsCancellationRequested && WakeAvailable() && api.Account.Email == owner;
            bool reset = wakeRecording;
            wakeWorker = null; wakeCancellation = null; wakeRecording = false; wakeReady = false;
            cancellation.Dispose();
            if (reset && !busy && !speaking) Idle();
            RefreshWakeIndicator();
            if (forward) await Safe(() => TranscribeVoice(audio, owner, voiceIdentityEpoch));
            else if (audio != null) Array.Clear(audio, 0, audio.Length);
            else if (reset && !busy && !speaking && !closed && wakeError.Length == 0) SetStatus("Команда не услышана. Можно снова сказать «Тройка».", false);
        }
        private void CancelWakeCapture() {
            if (wakeCancellation != null) wakeCancellation.Cancel();
            if (wakeRecording && !busy && !speaking) Idle();
            wakeRecording = false; wakeReady = false;
        }
        private async Task ReleaseWakeMicrophone() {
            wakeTransition++;
            try {
                var capture = wakeWorker;
                CancelWakeCapture();
                if (capture != null) { try { await capture; } catch { /* Reported by the capture observer. */ } }
            } finally { wakeTransition--; }
        }
        private void SetWakeEnabled(bool enabled) {
            wakeEnabled = enabled && api.Account.SignedIn;
            wakeOwner = wakeEnabled ? LocalStore.Hash(System.Text.Encoding.UTF8.GetBytes(api.Account.Email.ToLowerInvariant())) : "";
            wakeError = ""; wakeRetry = DateTime.MinValue;
            SaveSettings();
            ReconcileBackgroundVoice();
        }
        private bool WakeEnabledForAccount {
            get { return wakeEnabled && api.Account.SignedIn && wakeOwner == LocalStore.Hash(System.Text.Encoding.UTF8.GetBytes(api.Account.Email.ToLowerInvariant())); }
        }
        private string WakeStatus() {
            if (!WakeEnabledForAccount) return "Фоновое пробуждение выключено";
            if (wakeRecording) return "Тройка слушает команду";
            if (wakeReady) return "Тройка ждёт слово «Тройка»";
            if (wakeError.Length > 0) return wakeError;
            return WakeAvailable() ? "Запускаю фоновый микрофон…" : "Фоновый микрофон на паузе";
        }
        private void RefreshWakeIndicator() {
            if (wakeBadge != null) wakeBadge.Text = WakeStatus();
            RefreshBackgroundTray();
        }
        private void DisposeBackgroundVoice() {
            wakeTimer.Stop(); wakeEnabled = false; CancelWakeCapture();
            SystemEvents.SessionSwitch -= WakeSessionSwitch;
            SystemEvents.PowerModeChanged -= WakePowerChanged;
            var capture = wakeWorker;
            if (capture == null) voiceSignatures.Dispose();
            else capture.ContinueWith(_ => voiceSignatures.Dispose(), TaskScheduler.Default);
        }
    }
}
