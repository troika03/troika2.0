using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Threading;
using Troika.Desktop;

static class ComputerUseExternalEditor {
    [STAThread] public static int Main(string[] args) {
        if (args.Length == 1 && args[0] == "--verify") return Verify(null, ComputerUseExecutor.Sample);
        bool interactive = args.Length == 4 && args[0] == "--run";
        bool verifyRun = args.Length == 5 && args[0] == "--verify-run";
        if (!interactive && !verifyRun) {
            Console.Error.WriteLine("Usage: TroikaComputerUseEditor.exe --run <loopback-api> <run-id> <grant-id>");
            return 2;
        }
        try {
            using (var run = new ComputerUseWindowsRun(args[1],
                    Environment.GetEnvironmentVariable("TROIKA_COMPUTER_TEST_DEVICE_TOKEN"), args[2], args[3])) {
                if (verifyRun) return Verify(run, args[4]);
                var app = new Application();
                return app.Run(NewEditor(run));
            }
        } catch (ArgumentException error) {
            Console.Error.WriteLine(error.Message);
            return 2;
        }
    }

    private static ComputerUsePrototypeWindow NewEditor(ComputerUseWindowsRun run) {
        return new ComputerUsePrototypeWindow(new ComputerUseSession(), windowsRun: run, externalEditor: true);
    }

    private static int Verify(ComputerUseWindowsRun run, string expected) {
        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        app.Dispatcher.BeginInvoke(new Action(async () => {
            try {
                await CheckSavedFile(run, expected);
                if (run == null) {
                    await CheckValueGateAndStop();
                    await CheckPasswordField();
                }
                app.Shutdown(0);
            } catch (Exception error) {
                Console.Error.WriteLine(error.Message);
                app.Shutdown(1);
            }
        }));
        return app.Run();
    }

    private static async Task<ComputerUsePrototypeWindow> OpenForTest(ComputerUseWindowsRun run) {
        var window = NewEditor(run);
        window.ShowActivated = false;
        window.ShowInTaskbar = false;
        window.WindowStartupLocation = WindowStartupLocation.Manual;
        window.Left = -10000;
        window.Top = -10000;
        window.Show();
        await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        return window;
    }

    private static async Task CheckSavedFile(ComputerUseWindowsRun run, string expected) {
        var window = await OpenForTest(run);
        try {
            Require(window.Execution == null && !File.Exists(window.OutputFile), "The external editor acted before consent.");
            Click(window.AllowButton);
            Require(await Bounded(window.Execution) == ComputerUseState.Verified, "The external editor could not verify its save.");
            Require(File.ReadAllBytes(window.OutputFile).SequenceEqual(Encoding.UTF8.GetBytes(expected)),
                "The external editor saved different bytes.");
            Console.WriteLine("PASS Troika UI Automation controlled a separate editor executable and verified the file");
        } finally { Cleanup(window); }
    }

    private static async Task CheckValueGateAndStop() {
        var window = await OpenForTest(null);
        try {
            var handle = new WindowInteropHelper(window).Handle;
            var windowId = AutomationProperties.GetAutomationId(window);
            var driver = new ComputerUseNativeDriver(handle, windowId, true, externalEditor: true);
            await RejectNative(() => driver.SetEditorValue(ComputerUseExecutor.Sample),
                "ValuePattern wrote before consent.");
            Require(await Task.Run(() => driver.ReadEditor()) == "", "A rejected input changed the field.");
            Require(window.Session.Allow(), "Could not open the external editor grant.");

            var executor = new ComputerUseExecutor(window.Session, handle, windowId, window.OutputFile, externalEditor: true);
            var view = await Bounded(executor.InspectAsync());
            Require(view != null && view.CanWrite, "Could not inspect the external field.");
            int freshnessChecks = 0;
            var stale = await Bounded(executor.WriteAsync(view.Id, ComputerUseExecutor.Sample,
                () => Interlocked.Increment(ref freshnessChecks) == 1));
            Require(stale == ComputerUseCommandResult.StaleObservation && await Task.Run(() => driver.ReadEditor()) == "",
                "ValuePattern used an expired permit.");

            var write = window.Session.Arm(ComputerUseStep.Write, ComputerUseExecutor.Sample);
            Require(write != null, "Could not arm the external write.");
            await RejectNative(() => driver.SetEditorValue("Different test value"),
                "ValuePattern accepted text outside the permit.");
            await Task.Run(() => driver.SetEditorValue(ComputerUseExecutor.Sample));
            Require(await Bounded(write.Result.Task) && await Task.Run(() => driver.ReadEditor()) == ComputerUseExecutor.Sample,
                "The permitted ValuePattern write did not reach the editor.");
            Console.WriteLine("PASS standard ValuePattern input requires a fresh permit for the exact text");

            var save = window.Session.Arm(ComputerUseStep.Save, ComputerUseExecutor.Sample);
            Require(save != null, "Could not arm the external save.");
            Click(window.StopButton);
            await Task.Run(() => driver.Invoke("save"));
            await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            Require(window.Session.State == ComputerUseState.Stopped && !await Bounded(save.Result.Task)
                && !File.Exists(window.OutputFile), "The external editor saved after Stop.");
            Console.WriteLine("PASS the separate editor revoked a queued native save at local Stop");
        } finally { Cleanup(window); }
    }

    private static async Task CheckPasswordField() {
        var window = await OpenForTest(null);
        try {
            var id = AutomationProperties.GetAutomationId(window);
            var field = new PasswordBox { Password = "Synthetic fixture password" };
            AutomationProperties.SetAutomationId(field, id + "-editor");
            window.Content = field;
            await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            var driver = new ComputerUseNativeDriver(new WindowInteropHelper(window).Handle, id, true, externalEditor: true);
            await RejectNative(() => { driver.ReadEditor(); }, "The native worker read a password field.");
            Console.WriteLine("PASS the external worker rejects a password field before reading");
        } finally { Cleanup(window); }
    }

    private static async Task RejectNative(Action action, string message) {
        try { await Task.Run(action); }
        catch (IOException) { return; }
        throw new InvalidOperationException(message);
    }

    private static async Task<T> Bounded<T>(Task<T> task) {
        Require(task != null && await Task.WhenAny(task, Task.Delay(25000)) == task, "The external editor timed out.");
        return await task;
    }

    private static void Require(bool condition, string message) {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void Click(Button button) { button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }

    private static void Cleanup(ComputerUsePrototypeWindow window) {
        window.Close();
        if (File.Exists(window.OutputFile)) File.Delete(window.OutputFile);
        var folder = Path.GetDirectoryName(window.OutputFile);
        if (Directory.Exists(folder)) Directory.Delete(folder, false);
    }
}
