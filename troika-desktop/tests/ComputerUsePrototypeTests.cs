using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Threading;
using Troika.Desktop;

static class ComputerUsePrototypeTests {
    private static void Assert(bool expected, string reason) {
        if (!expected) throw new InvalidOperationException(reason);
    }

    private static void Click(Button button) { button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }

    private static void CheckConsentAndExpiry() {
        TimeSpan now = TimeSpan.Zero;
        var declined = new ComputerUseSession(() => now);
        declined.Stop();
        Assert(!declined.Allow(), "Stopping before consent did not close the request.");
        var session = new ComputerUseSession(() => now);
        Assert(session.Arm(ComputerUseStep.Write) == null, "A write was accepted before consent.");
        Assert(session.Allow() && !session.Allow(), "Consent must start a single session.");
        Assert(session.Arm(ComputerUseStep.Save) == null, "A save was accepted before a write.");
        var permit = session.Arm(ComputerUseStep.Write);
        Assert(permit != null && session.Consume(ComputerUseStep.Write) == permit, "A permitted write could not start.");
        Assert(session.Consume(ComputerUseStep.Write) == null, "A repeated write callback got permission.");
        now = TimeSpan.FromSeconds(ComputerUseSession.ConsentSeconds);
        Assert(session.State == ComputerUseState.Expired && permit.Result.Task.IsCompleted && !permit.Result.Task.Result,
            "Expiry must close the grant and release a waiting executor.");
        session.Report(permit, true);
        Assert(session.Arm(ComputerUseStep.Save) == null && session.Finish(true) == ComputerUseState.Expired,
            "A late receipt revived an expired grant.");
        Console.WriteLine("PASS consent, action order, replay rejection and exact expiry");
    }

    private static ComputerUsePrototypeWindow Open() {
        var window = new ComputerUsePrototypeWindow {
            ShowActivated = false, ShowInTaskbar = false,
            WindowStartupLocation = WindowStartupLocation.Manual, Left = -10000, Top = -10000,
        };
        window.Show();
        window.UpdateLayout();
        return window;
    }

    private static void Cleanup(ComputerUsePrototypeWindow window) {
        window.Close();
        if (File.Exists(window.OutputFile)) File.Delete(window.OutputFile);
        var folder = Path.GetDirectoryName(window.OutputFile);
        if (Directory.Exists(folder)) Directory.Delete(folder, false);
    }

    private static async Task<T> Bounded<T>(Task<T> task) {
        Assert(task != null && await Task.WhenAny(task, Task.Delay(12000)) == task, "The prototype did not finish within 12 seconds.");
        return await task;
    }

    private static async Task CheckNativeSave() {
        var window = Open();
        try {
            Assert(window.AllowButton.IsVisible && window.StopButton.IsVisible, "Consent and Stop must be visible in the prototype window.");
            Assert(!File.Exists(window.OutputFile), "Opening the window created a file without consent.");
            Click(window.AllowButton);
            Assert(await Bounded(window.Execution) == ComputerUseState.Verified, "The native write, save and readback were not verified.");
            Assert(File.ReadAllText(window.OutputFile) == ComputerUseExecutor.Sample, "The saved sample does not match.");
            Console.WriteLine("PASS native UI Automation write, save and exact file readback");
        } finally { Cleanup(window); }
    }

    private static AutomationElement FindFixture(IntPtr handle, string id) {
        var root = AutomationElement.FromHandle(handle);
        var control = root.FindFirst(TreeScope.Descendants, new PropertyCondition(AutomationElement.AutomationIdProperty, id));
        Assert(control != null, "The native test control is unavailable.");
        return control;
    }

    private static void InvokeFixture(IntPtr handle, string id) {
        ((InvokePattern)FindFixture(handle, id).GetCurrentPattern(InvokePattern.Pattern)).Invoke();
    }

    private static async Task CheckLateSaveAfterStop() {
        var window = Open();
        try {
            var handle = new WindowInteropHelper(window).Handle;
            string id = AutomationProperties.GetAutomationId(window);
            Assert(window.Session.Allow(), "Consent could not be set for the fixture.");
            var write = window.Session.Arm(ComputerUseStep.Write);
            await Task.Run(() => InvokeFixture(handle, id + "-write"));
            Assert(await Bounded(write.Result.Task), "The fixture did not receive the native write.");

            var save = window.Session.Arm(ComputerUseStep.Save);
            Assert(save != null, "Save was not pending before Stop.");
            Click(window.StopButton);
            await Task.Run(() => InvokeFixture(handle, id + "-save"));
            await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            Assert(window.Session.State == ComputerUseState.Stopped && !await Bounded(save.Result.Task), "Local Stop did not revoke the pending save.");
            Assert(!File.Exists(window.OutputFile), "A native callback saved a file after Stop.");
            var text = await Task.Run(() => ((ValuePattern)FindFixture(handle, id + "-editor")
                .GetCurrentPattern(ValuePattern.Pattern)).Current.Value);
            Assert(text == ComputerUseExecutor.Sample, "Stop should preserve the completed write.");
            Console.WriteLine("PASS Stop blocks a late native callback without network");
        } finally { Cleanup(window); }
    }

    private static async Task CheckNoOverwrite() {
        var window = Open();
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(window.OutputFile));
            File.WriteAllText(window.OutputFile, "Existing test fixture");
            Click(window.AllowButton);
            Assert(await Bounded(window.Execution) == ComputerUseState.Failed, "An existing file was reported as a successful save.");
            Assert(File.ReadAllText(window.OutputFile) == "Existing test fixture", "The test file was overwritten.");
            Console.WriteLine("PASS save refuses to overwrite an existing file");
        } finally { Cleanup(window); }
    }

    private static async Task CheckWindowIdentity() {
        var window = Open();
        try {
            Assert(window.Session.Allow(), "Could not start the fixture grant.");
            var wrongWindow = new ComputerUseExecutor(window.Session, new WindowInteropHelper(window).Handle,
                "different-window-identity", window.OutputFile);
            Assert(await Bounded(wrongWindow.RunAsync()) == ComputerUseState.Failed, "An unapproved window was accepted.");
            Assert(!File.Exists(window.OutputFile), "The wrong window produced a file.");
            Console.WriteLine("PASS native window identity check");
        } finally { Cleanup(window); }
    }

    [STAThread] public static int Main() {
        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        app.Dispatcher.BeginInvoke(new Action(async () => {
            try {
                CheckConsentAndExpiry();
                await CheckNativeSave();
                await CheckLateSaveAfterStop();
                await CheckNoOverwrite();
                await CheckWindowIdentity();
                app.Shutdown(0);
            } catch (Exception error) {
                Console.Error.WriteLine(error.Message);
                app.Shutdown(1);
            }
        }));
        return app.Run();
    }
}
