using System;
using System.ComponentModel;
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
        private readonly ComputerUseNativeDriver driver;
        private readonly string output;
        private readonly Func<TimeSpan> clock;
        private readonly bool externalEditor;
        private ComputerUseObservation observation;
        private TimeSpan observationExpiry;
        private string writtenText;

        internal ComputerUseExecutor(ComputerUseSession session, IntPtr handle, string windowId, string output,
                Func<TimeSpan> clock = null, bool isolated = false, bool externalEditor = false) {
            this.session = session;
            driver = new ComputerUseNativeDriver(handle, windowId, isolated, externalEditor);
            this.output = output;
            this.externalEditor = externalEditor;
            this.clock = clock ?? (() => ObservationClock.Elapsed);
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

        internal Task<ComputerUseCommandResult> WriteAsync(Guid observationId, string text, Func<bool> commandIsFresh = null) {
            return ExecuteAsync(() => {
                if (session.State != ComputerUseState.Active) return ComputerUseCommandResult.NotActive;
                if (!ValidText(text)) return ComputerUseCommandResult.InvalidText;
                if (!IsCurrent(observationId) || !observation.CanWrite || ReadEditor().Length != 0 || !IsCurrent(observationId))
                    return ComputerUseCommandResult.StaleObservation;
                var result = Invoke(ComputerUseStep.Write, "write", text, observationId, commandIsFresh);
                if (result != ComputerUseCommandResult.Applied) return result;
                if (ReadEditor() != text) return Fail();
                writtenText = text;
                return ComputerUseCommandResult.Applied;
            }, ComputerUseCommandResult.Failed);
        }

        internal Task<ComputerUseCommandResult> SaveAsync(Guid observationId, Func<bool> commandIsFresh = null) {
            return ExecuteAsync(() => {
                if (session.State != ComputerUseState.Active) return ComputerUseCommandResult.NotActive;
                if (!IsCurrent(observationId) || !observation.CanSave || ReadEditor() != writtenText || !IsCurrent(observationId))
                    return ComputerUseCommandResult.StaleObservation;
                var result = Invoke(ComputerUseStep.Save, "save", writtenText, observationId, commandIsFresh);
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
                    catch (Win32Exception) { }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                    catch (ArgumentException) { }
                    catch (FormatException) { }
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

        internal static bool ValidText(string text) {
            if (string.IsNullOrEmpty(text) || text.Length > MaxTextLength) return false;
            foreach (char character in text)
                if (char.IsControl(character) || character == '\u2028' || character == '\u2029') return false;
            try { StrictUtf8.GetByteCount(text); return true; }
            catch (EncoderFallbackException) { return false; }
        }

        private string ReadEditor() {
            if (session.State != ComputerUseState.Active) throw new InvalidOperationException();
            return driver.ReadEditor();
        }

        private ComputerUseCommandResult Invoke(ComputerUseStep step, string suffix, string text, Guid observationId,
                Func<bool> commandIsFresh) {
            if (!IsCurrent(observationId) || (commandIsFresh != null && !commandIsFresh()))
                return ComputerUseCommandResult.StaleObservation;
            observation = null;
            var expiresAt = observationExpiry;
            var permit = session.Arm(step, text, () => clock() < expiresAt && (commandIsFresh == null || commandIsFresh()));
            if (permit == null) return session.State == ComputerUseState.Active ? Fail() : ComputerUseCommandResult.NotActive;
            try {
                if (externalEditor && step == ComputerUseStep.Write) driver.SetEditorValue(text);
                else driver.Invoke(suffix);
            } catch (IOException) {
                if (permit.Result.Task.IsCompleted && permit.ObservationExpired)
                    return ComputerUseCommandResult.StaleObservation;
                if (session.State != ComputerUseState.Active) return ComputerUseCommandResult.NotActive;
                throw;
            }
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
