using System;
using System.IO;
using System.Linq;
using System.Text;
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
                if (run == null) await CheckStop();
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

    private static async Task CheckStop() {
        var window = await OpenForTest(null);
        try {
            var driver = new ComputerUseNativeDriver(new WindowInteropHelper(window).Handle,
                AutomationProperties.GetAutomationId(window), true, externalEditor: true);
            Require(window.Session.Allow(), "Could not open the external editor grant.");
            var write = window.Session.Arm(ComputerUseStep.Write, ComputerUseExecutor.Sample);
            Require(write != null, "Could not arm the external write.");
            await Task.Run(() => driver.Invoke("write"));
            Require(await Bounded(write.Result.Task), "The external write did not reach the editor.");
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
