using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Automation;

namespace Troika.Desktop {
    internal enum ComputerUseCommandResult { Applied, Verified, StaleObservation, InvalidText, NotActive, Failed }

    internal sealed class ComputerUseObservation {
        internal readonly Guid Id = Guid.NewGuid();
        internal readonly bool CanWrite;
        internal readonly bool CanSave;

        internal ComputerUseObservation(bool canWrite, bool canSave) { CanWrite = canWrite; CanSave = canSave; }
    }

    internal sealed class ComputerUseExecutor {
        internal const string Sample = "Пробная запись Тройки.";
        internal const int ObservationSeconds = 15;
        private const int MaxTextLength = 512;
        private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);
        private readonly object commandGate = new object();
        private readonly ComputerUseSession session;
        private readonly IntPtr handle;
        private readonly string windowId;
        private readonly string output;
        private readonly int processId;
        private readonly Func<TimeSpan> clock;
        private ComputerUseObservation observation;
        private TimeSpan observationExpiry;
        private string writtenText;

        internal ComputerUseExecutor(ComputerUseSession session, IntPtr handle, string windowId, string output, Func<TimeSpan> clock = null) {
            this.session = session;
            this.handle = handle;
            this.windowId = windowId;
            this.output = output;
            this.clock = clock ?? (() => ObservationClock.Elapsed);
            using (var process = Process.GetCurrentProcess()) processId = process.Id;
        }
        private static readonly Stopwatch ObservationClock = Stopwatch.StartNew();

        // UI Automation can marshal to this WPF window. Keep every provider
        // call on the worker so the owner dispatcher can process Stop.
        internal Task<ComputerUseObservation> InspectAsync() {
            return ExecuteAsync(() => {
                observation = null;
                if (session.State != ComputerUseState.Active) return null;
                var text = ReadEditor();
                if (session.State != ComputerUseState.Active) return null;
                observation = new ComputerUseObservation(writtenText == null && text.Length == 0,
                    writtenText != null && text == writtenText);
                observationExpiry = clock().Add(TimeSpan.FromSeconds(ObservationSeconds));
                return observation;
            }, (ComputerUseObservation)null);
        }

        internal Task<ComputerUseCommandResult> WriteAsync(Guid observationId, string text) {
            return ExecuteAsync(() => {
                if (session.State != ComputerUseState.Active) return ComputerUseCommandResult.NotActive;
                if (!ValidText(text)) return ComputerUseCommandResult.InvalidText;
                if (!IsCurrent(observationId) || !observation.CanWrite || ReadEditor().Length != 0 || !IsCurrent(observationId))
                    return ComputerUseCommandResult.StaleObservation;
                var result = Invoke(ComputerUseStep.Write, "write", text, observationId);
                if (result != ComputerUseCommandResult.Applied) return result;
                if (ReadEditor() != text) return Fail();
                writtenText = text;
                return ComputerUseCommandResult.Applied;
            }, ComputerUseCommandResult.Failed);
        }

        internal Task<ComputerUseCommandResult> SaveAsync(Guid observationId) {
            return ExecuteAsync(() => {
                if (session.State != ComputerUseState.Active) return ComputerUseCommandResult.NotActive;
                if (!IsCurrent(observationId) || !observation.CanSave || ReadEditor() != writtenText || !IsCurrent(observationId))
                    return ComputerUseCommandResult.StaleObservation;
                var result = Invoke(ComputerUseStep.Save, "save", writtenText, observationId);
                if (result != ComputerUseCommandResult.Applied) return result;
                return session.Finish(VerifyFile(writtenText)) == ComputerUseState.Verified
                    ? ComputerUseCommandResult.Verified : ComputerUseCommandResult.Failed;
            }, ComputerUseCommandResult.Failed);
        }

        internal async Task<ComputerUseState> RunAsync() {
            var start = await InspectAsync().ConfigureAwait(false);
            if (start == null || await WriteAsync(start.Id, Sample).ConfigureAwait(false) != ComputerUseCommandResult.Applied)
                return session.Finish(false);
            var written = await InspectAsync().ConfigureAwait(false);
            if (written == null || await SaveAsync(written.Id).ConfigureAwait(false) != ComputerUseCommandResult.Verified)
                return session.Finish(false);
            return session.State;
        }

        private Task<T> ExecuteAsync<T>(Func<T> command, T failure) {
            return Task.Run(() => {
                lock (commandGate) {
                    try { return command(); }
                    catch (ElementNotAvailableException) { }
                    catch (ElementNotEnabledException) { }
                    catch (InvalidOperationException) { }
                    catch (COMException) { }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                    Fail();
                    return failure;
                }
            });
        }

        private ComputerUseCommandResult Fail() {
            observation = null;
            session.Finish(false);
            return ComputerUseCommandResult.Failed;
        }

        private bool IsCurrent(Guid id) {
            return observation != null && observation.Id == id && clock() < observationExpiry;
        }

        private static bool ValidText(string text) {
            if (string.IsNullOrEmpty(text) || text.Length > MaxTextLength) return false;
            foreach (char character in text) if (char.IsControl(character)) return false;
            try { StrictUtf8.GetByteCount(text); return true; }
            catch (EncoderFallbackException) { return false; }
        }

        private AutomationElement Find(string suffix, ControlType type) {
            if (handle == IntPtr.Zero || session.State != ComputerUseState.Active) throw new InvalidOperationException();
            var root = AutomationElement.FromHandle(handle);
            if (root.Current.ProcessId != processId || root.Current.AutomationId != windowId) throw new InvalidOperationException();
            var element = root.FindFirst(TreeScope.Descendants, new AndCondition(
                new PropertyCondition(AutomationElement.AutomationIdProperty, windowId + "-" + suffix),
                new PropertyCondition(AutomationElement.ControlTypeProperty, type)));
            if (element == null || element.Current.ProcessId != processId) throw new InvalidOperationException();
            return element;
        }

        private string ReadEditor() {
            var editor = Find("editor", ControlType.Edit);
            return ((ValuePattern)editor.GetCurrentPattern(ValuePattern.Pattern)).Current.Value;
        }

        private ComputerUseCommandResult Invoke(ComputerUseStep step, string suffix, string text, Guid observationId) {
            var button = Find(suffix, ControlType.Button);
            var pattern = (InvokePattern)button.GetCurrentPattern(InvokePattern.Pattern);
            if (!IsCurrent(observationId)) return ComputerUseCommandResult.StaleObservation;
            observation = null;
            var expiresAt = observationExpiry;
            var permit = session.Arm(step, text, () => clock() < expiresAt);
            if (permit == null) return session.State == ComputerUseState.Active ? Fail() : ComputerUseCommandResult.NotActive;
            pattern.Invoke();
            if (!permit.Result.Task.Wait(TimeSpan.FromSeconds(2))) return Fail();
            if (permit.Result.Task.Result) return ComputerUseCommandResult.Applied;
            return permit.ObservationExpired ? ComputerUseCommandResult.StaleObservation : Fail();
        }

        private bool VerifyFile(string text) {
            if (session.State != ComputerUseState.Active) return false;
            byte[] expected = StrictUtf8.GetBytes(text);
            using (var file = new FileStream(output, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                if (file.Length != expected.Length) return false;
                foreach (byte item in expected) if (file.ReadByte() != item) return false;
                return file.ReadByte() == -1;
            }
        }
    }
}
