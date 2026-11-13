using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    internal sealed class ComputerUseNotepadControl : IDisposable {
        private readonly ComputerUseSession session = new ComputerUseSession();
        private readonly string path;
        private ComputerUseNotepad document;
        private ComputerUseExecutor executor;
        private ComputerUsePointer pointer;
        internal string SavedFile { get { return session.State == ComputerUseState.Verified ? path : null; } }

        internal ComputerUseNotepadControl() {
            string id = "troika-notepad-" + Guid.NewGuid().ToString("N");
            path = Path.Combine(Path.GetTempPath(), id, id + ".txt");
        }

        internal async Task<object> Execute(string action, string text, TimeSpan remaining,
                Func<CancellationToken, Task<bool>> stillAllowed, CancellationToken cancellation) {
            var clock = Stopwatch.StartNew();
            Func<bool> fresh = () => !cancellation.IsCancellationRequested && clock.Elapsed < remaining;
            if (!fresh()) throw new OperationCanceledException();
            using (cancellation.Register(session.Stop)) {
                if (action == "open") {
                    if (document != null || !session.Allow()) throw new InvalidOperationException();
                    document = await Task.Run(() => new ComputerUseNotepad(session, path, showForCapture: true));
                    executor = new ComputerUseExecutor(session, document, path, ComputerUseNotepad.FileEncoding, 30);
                }
                if (document == null) {
                    if (action != "inspect") throw new InvalidOperationException();
                    return View(false, false, false, false);
                }
                if (SavedFile != null && action == "inspect") return View(true, false, false, true);
                var observation = await executor.InspectAsync();
                if (observation == null || !fresh()) throw new InvalidOperationException();
                if (action == "write" || action == "save") {
                    bool write = action == "write";
                    if (write ? !observation.CanWrite : !observation.CanSave) throw new InvalidOperationException();
                    try {
                        await Preview(write ? ComputerUseStep.Write : ComputerUseStep.Save, fresh, cancellation);
                        if (!fresh() || !await stillAllowed(cancellation) || !fresh()) throw new OperationCanceledException();
                        if (write) {
                            if (await executor.WriteAsync(observation.Id, text, fresh) != ComputerUseCommandResult.Applied)
                                throw new InvalidOperationException();
                            observation = await executor.InspectAsync();
                            if (observation == null) throw new InvalidOperationException();
                        } else {
                            if (await executor.SaveAsync(observation.Id, fresh) != ComputerUseCommandResult.Verified)
                                throw new InvalidOperationException();
                            return View(true, false, false, true);
                        }
                    } finally { if (pointer != null) pointer.Hide(); }
                }
                return View(true, observation.CanWrite, observation.CanSave, false);
            }
        }

        private async Task Preview(ComputerUseStep step, Func<bool> fresh, CancellationToken cancellation) {
            try {
                if (pointer == null) pointer = new ComputerUsePointer();
                await pointer.Preview(document, step, fresh, cancellation);
            } catch (Win32Exception) {
                if (pointer != null) pointer.Hide();
            }
        }

        private static object View(bool open, bool canWrite, bool canSave, bool saved) {
            return new { open = open, can_write = canWrite, can_save = canSave, saved = saved };
        }

        public void Dispose() {
            session.Stop();
            if (pointer != null) pointer.Dispose();
            if (document != null) document.Dispose();
        }
    }
}
