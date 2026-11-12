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
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Troika.Desktop;

static class ComputerUseExternalEditor {
    [STAThread] public static int Main(string[] args) {
        if (args.Length == 1 && args[0] == "--verify") return Verify(null, ComputerUseExecutor.Sample);
        if (args.Length == 1 && args[0] == "--preview") return new Application().Run(new ComputerUseVisualPreview());
        bool interactive = args.Length == 4 && args[0] == "--run";
        bool verifyRun = args.Length == 5 && args[0] == "--verify-run";
        if (!interactive && !verifyRun) {
            Console.Error.WriteLine("Usage: TroikaComputerUseEditor.exe --preview | --run <loopback-api> <run-id> <grant-id>");
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
                    await CheckVisualPreview();
                    await CheckLateRecognition();
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

    private static async Task CheckVisualPreview() {
        var time = TimeSpan.Zero;
        var window = new ComputerUseVisualPreview(() => time) {
            ShowActivated = false,
            ShowInTaskbar = false,
            WindowStartupLocation = WindowStartupLocation.Manual,
            Left = -10000,
            Top = -10000,
            Width = 960
        };
        try {
            window.Show();
            await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            await Bounded(window.CaptureAsync());
            Require(window.Preview.Source == null, "The editor captured a frame before consent.");
            Click(window.AllowButton);
            await Bounded(window.CaptureAsync());
            var frame = window.Preview.Source as BitmapSource;
            Require(frame != null && frame.PixelWidth == 640 && frame.PixelHeight <= 240,
                "The preview did not respect the frame bounds.");
            if (ComputerUseVisualPreview.RussianOcrAvailable) {
                Require(window.Recognized.Text.Contains("Пробная запись Тройки"), "Windows OCR did not read the sample pixels.");
                Console.WriteLine("PASS Windows OCR recognized the Russian sample from the editor pixels");
            } else {
                Require(window.Recognized.Text.Contains("недоступно"), "The preview did not report the missing OCR language.");
                Console.WriteLine("SKIP Windows OCR recognition because the Russian language pack is absent");
            }

            var outsideColor = Color.FromRgb(245, 31, 151);
            var sibling = new Border { Background = new SolidColorBrush(outsideColor), Height = 30 };
            ((StackPanel)window.Content).Children.Insert(0, sibling);
            window.UpdateLayout();
            await Bounded(window.CaptureAsync());
            byte[] withSibling = FramePixels((BitmapSource)window.Preview.Source);
            Require(sibling.ActualWidth > 0 && sibling.ActualHeight > 0 && !ContainsColor(withSibling, outsideColor),
                "The frame included pixels from the visible sibling of the editor field.");
            window.Editor.Text = "";
            window.UpdateLayout();
            await Bounded(window.CaptureAsync());
            Require(!withSibling.SequenceEqual(FramePixels((BitmapSource)window.Preview.Source)),
                "The frame did not render the text field.");
            Require(!window.Recognized.Text.Contains("Пробная запись Тройки"), "OCR retained text from the previous frame.");

            time = TimeSpan.FromSeconds(15);
            await Task.Delay(250);
            Require(window.Preview.Source == null && window.Recognized.Text == "", "The preview retained an expired observation.");
            await Bounded(window.CaptureAsync());
            Require(window.Preview.Source != null, "A fresh frame was unavailable after expiry.");
            window.Hide();
            Require(window.Preview.Source == null && window.Recognized.Text == "", "Hiding the preview retained its observation.");
            window.Show();
            await Bounded(window.CaptureAsync());
            Require(window.Preview.Source != null, "The preview could not recapture after showing the window.");
            Click(window.StopButton);
            await Bounded(window.CaptureAsync());
            Require(window.Preview.Source == null && window.Recognized.Text == "", "The preview retained an observation after Stop.");
            Console.WriteLine("PASS visual preview captures only the bounded consented field and drops expired frames");
        } finally { window.Close(); }
    }

    private static async Task CheckLateRecognition() {
        var completion = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var window = new ComputerUseVisualPreview(recognize: frame => completion.Task) {
            ShowActivated = false,
            ShowInTaskbar = false,
            WindowStartupLocation = WindowStartupLocation.Manual,
            Left = -10000,
            Top = -10000
        };
        try {
            window.Show();
            await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            Click(window.AllowButton);
            var pending = window.CaptureAsync();
            Require(window.Preview.Source != null && !pending.IsCompleted, "No OCR request was pending before Stop.");
            Click(window.StopButton);
            completion.SetResult("Late OCR result");
            await Bounded(pending);
            Require(window.Preview.Source == null && window.Recognized.Text == "", "A late OCR result appeared after Stop.");
            Console.WriteLine("PASS local Stop discards an in-flight Windows OCR result");
        } finally { window.Close(); }
    }

    private static byte[] FramePixels(BitmapSource frame) {
        Require(frame != null, "The preview frame was missing.");
        int stride = frame.PixelWidth * 4;
        var bytes = new byte[stride * frame.PixelHeight];
        frame.CopyPixels(bytes, stride, 0);
        return bytes;
    }

    private static bool ContainsColor(byte[] pixels, Color color) {
        for (int index = 0; index < pixels.Length; index += 4)
            if (pixels[index] == color.B && pixels[index + 1] == color.G && pixels[index + 2] == color.R
                    && pixels[index + 3] == color.A) return true;
        return false;
    }

    private static async Task RejectNative(Action action, string message) {
        try { await Task.Run(action); }
        catch (IOException) { return; }
        throw new InvalidOperationException(message);
    }

    private static async Task<T> Bounded<T>(Task<T> task) {
        await Bounded((Task)task);
        return await task;
    }

    private static async Task Bounded(Task task) {
        Require(task != null && await Task.WhenAny(task, Task.Delay(25000)) == task, "The external editor timed out.");
        await task;
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
