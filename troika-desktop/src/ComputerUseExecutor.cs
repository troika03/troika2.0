using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Automation;

namespace Troika.Desktop {
    internal sealed class ComputerUseExecutor {
        internal const string Sample = "Пробная запись Тройки.";
        private readonly ComputerUseSession session;
        private readonly IntPtr handle;
        private readonly string windowId;
        private readonly string output;
        private readonly int processId;

        internal ComputerUseExecutor(ComputerUseSession session, IntPtr handle, string windowId, string output) {
            this.session = session;
            this.handle = handle;
            this.windowId = windowId;
            this.output = output;
            using (var process = Process.GetCurrentProcess()) processId = process.Id;
        }

        // UI Automation can marshal to this WPF window. Keep every provider
        // call on the worker so the owner dispatcher can process Stop.
        internal Task<ComputerUseState> RunAsync() { return Task.Run(() => Run()); }

        private ComputerUseState Run() {
            try {
                if (session.State != ComputerUseState.Active) return session.State;
                if (ReadEditor() != string.Empty) return session.Finish(false);
                if (!Invoke(ComputerUseStep.Write, "write") || ReadEditor() != Sample) return session.Finish(false);
                if (!Invoke(ComputerUseStep.Save, "save")) return session.Finish(false);
                return session.Finish(VerifyFile());
            } catch (ElementNotAvailableException) { return session.Finish(false); }
            catch (ElementNotEnabledException) { return session.Finish(false); }
            catch (InvalidOperationException) { return session.Finish(false); }
            catch (COMException) { return session.Finish(false); }
            catch (IOException) { return session.Finish(false); }
            catch (UnauthorizedAccessException) { return session.Finish(false); }
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

        private bool Invoke(ComputerUseStep step, string suffix) {
            var button = Find(suffix, ControlType.Button);
            var pattern = (InvokePattern)button.GetCurrentPattern(InvokePattern.Pattern);
            var permit = session.Arm(step);
            if (permit == null) return false;
            pattern.Invoke();
            return permit.Result.Task.Wait(TimeSpan.FromSeconds(2)) && permit.Result.Task.Result;
        }

        private bool VerifyFile() {
            if (session.State != ComputerUseState.Active) return false;
            byte[] expected = Encoding.UTF8.GetBytes(Sample);
            using (var file = new FileStream(output, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                if (file.Length != expected.Length) return false;
                foreach (byte item in expected) if (file.ReadByte() != item) return false;
                return file.ReadByte() == -1;
            }
        }
    }
}
