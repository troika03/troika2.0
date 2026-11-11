using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;

namespace Troika.Desktop {
    internal sealed class ComputerUseNativeDriver {
        internal const string WorkerArgument = "--computer-use-native-worker";
        private const string TargetPrefix = "troika-scratchpad-";
        private const int TimeoutMilliseconds = 5000;
        private const int MaxEncodedEditorLength = 2048;
        private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);
        private readonly IntPtr handle;
        private readonly string windowId;
        private readonly int processId;
        private readonly string workerImage;

        internal ComputerUseNativeDriver(IntPtr handle, string windowId, bool isolated) {
            this.handle = handle;
            this.windowId = windowId;
            using (var process = Process.GetCurrentProcess()) {
                processId = process.Id;
                if (isolated) workerImage = process.MainModule.FileName;
            }
        }

        private ComputerUseNativeDriver(IntPtr handle, string windowId, int processId) {
            this.handle = handle;
            this.windowId = windowId;
            this.processId = processId;
        }

        internal string ReadEditor() {
            if (workerImage == null) return ReadNative();
            var encoded = RunWorker("editor");
            if (encoded.Length > MaxEncodedEditorLength) throw new InvalidDataException();
            return StrictUtf8.GetString(Convert.FromBase64String(encoded));
        }

        internal void Invoke(string action) {
            if (workerImage == null) InvokeNative(action);
            else if (RunWorker(action) != "") throw new InvalidDataException();
        }

        private string RunWorker(string action) {
            // The worker gets only a fixture identity and operation, never the goal or provider key.
            var start = new ProcessStartInfo(workerImage, string.Format(CultureInfo.InvariantCulture,
                "{0} {1} {2} {3} {4}", WorkerArgument, processId, handle.ToInt64(), windowId, action)) {
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                StandardOutputEncoding = Encoding.ASCII,
            };
            start.EnvironmentVariables.Clear();
            start.EnvironmentVariables["SystemRoot"] = Environment.GetEnvironmentVariable("SystemRoot");
            using (var worker = Process.Start(start)) {
                if (worker == null) throw new InvalidOperationException();
                if (!worker.WaitForExit(TimeoutMilliseconds)) {
                    try { worker.Kill(); } catch (InvalidOperationException) { }
                    throw new IOException("The native UI worker timed out.");
                }
                if (worker.ExitCode != 0) throw new IOException("The native UI worker rejected the operation.");
                return worker.StandardOutput.ReadToEnd();
            }
        }

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr window, out uint owner);

        private AutomationElement Find(string suffix, ControlType type) {
            uint owner;
            if (handle == IntPtr.Zero || GetWindowThreadProcessId(handle, out owner) == 0 || owner != processId)
                throw new InvalidOperationException();
            var root = AutomationElement.FromHandle(handle);
            if (root.Current.ProcessId != processId || root.Current.AutomationId != windowId) throw new InvalidOperationException();
            var element = root.FindFirst(TreeScope.Descendants, new AndCondition(
                new PropertyCondition(AutomationElement.AutomationIdProperty, windowId + "-" + suffix),
                new PropertyCondition(AutomationElement.ControlTypeProperty, type)));
            if (element == null || element.Current.ProcessId != processId) throw new InvalidOperationException();
            return element;
        }

        private string ReadNative() {
            var editor = Find("editor", ControlType.Edit);
            return ((ValuePattern)editor.GetCurrentPattern(ValuePattern.Pattern)).Current.Value;
        }

        private void InvokeNative(string action) {
            if (action != "write" && action != "save") throw new InvalidOperationException();
            var button = Find(action, ControlType.Button);
            ((InvokePattern)button.GetCurrentPattern(InvokePattern.Pattern)).Invoke();
        }

        internal static int WorkerMain(string[] args) {
            int pid;
            long rawHandle;
            Guid id;
            if (args.Length != 5 || !int.TryParse(args[1], NumberStyles.None, CultureInfo.InvariantCulture, out pid)
                    || pid <= 0 || !long.TryParse(args[2], NumberStyles.None, CultureInfo.InvariantCulture, out rawHandle)
                    || rawHandle == 0 || !args[3].StartsWith(TargetPrefix, StringComparison.Ordinal)
                    || !Guid.TryParseExact(args[3].Substring(TargetPrefix.Length), "N", out id))
                return 2;
            try {
                using (var self = Process.GetCurrentProcess())
                using (var target = Process.GetProcessById(pid)) {
                    if (self.Id == pid || !String.Equals(self.MainModule.FileName, target.MainModule.FileName, StringComparison.OrdinalIgnoreCase))
                        return 2;
                    var driver = new ComputerUseNativeDriver(new IntPtr(rawHandle), args[3], pid);
                    if (args[4] == "editor") {
                        var encoded = Convert.ToBase64String(StrictUtf8.GetBytes(driver.ReadNative()));
                        if (encoded.Length > MaxEncodedEditorLength) return 2;
                        Console.Write(encoded);
                    } else {
                        driver.InvokeNative(args[4]);
                    }
                    return 0;
                }
            } catch (ElementNotAvailableException) { }
            catch (ElementNotEnabledException) { }
            catch (InvalidOperationException) { }
            catch (COMException) { }
            catch (Win32Exception) { }
            catch (IOException) { }
            catch (ArgumentException) { }
            return 2;
        }
    }
}
