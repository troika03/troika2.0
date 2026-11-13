using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Troika.Desktop;

internal static class ComputerUseDeviceUiTests {
    private const string Expected = "Проба Тройки";

    [STAThread] public static int Main(string[] args) {
        Console.OutputEncoding = Encoding.UTF8;
        bool layout = args.Length >= 1 && args[0] == "--layout";
        if (!(layout && args.Length <= 2) && !(args.Length == 3 && new[] { "--run", "--stop", "--click" }.Contains(args[0]))) return 2;
        using (var run = layout ? null : new ComputerUseDeviceRun(args[1], args[2],
                Environment.GetEnvironmentVariable("TROIKA_COMPUTER_TEST_DEVICE_TOKEN"))) {
            var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
            app.Startup += (sender, eventArgs) => app.Dispatcher.BeginInvoke(new Action(async () => {
                var window = new ComputerUseDeviceWindow(run) { ShowActivated = false, ShowInTaskbar = false };
                int exit = 0;
                try {
                    window.Show();
                    await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                    Require(window.Permission.Items.Count == 3 && window.Permission.SelectedIndex == 0, "The default permission must ask.");
                    Require(window.StartButton.IsEnabled && !window.StopButton.IsEnabled && !window.ApproveButton.IsVisible,
                        "The idle controls do not match the Run state.");
                    window.Browser.IsChecked = window.Notepad.IsChecked = false;
                    Require(!window.StartButton.IsEnabled, "The Run accepted an empty scope.");
                    window.Browser.IsChecked = window.Notepad.IsChecked = true;
                    if (layout) {
                        if (args.Length == 2) Render(window, args[1]);
                        Console.WriteLine("PASS Windows Computer Use shares one permission menu and requires an approved app.");
                    } else await Verify(window, args[0] == "--stop", args[0] == "--click");
                } catch (Exception error) {
                    Console.Error.WriteLine(error.Message);
                    exit = 1;
                }
                if (window.StopButton.IsEnabled) Click(window.StopButton);
                if (window.Execution != null) await window.Execution;
                window.Close();
                app.Shutdown(exit);
            }));
            return app.Run();
        }
    }

    private static async Task Verify(ComputerUseDeviceWindow window, bool stop, bool click) {
        window.Goal.Text = "Сначала осмотри Блокнот, открой его, введи ровно «" + Expected +
            "» без кавычек и сохрани. Затем осмотри браузер, открой overview и "
            + (click ? "нажми видимую ссылку «Доставка». " : "прокрути до раздела доставки. ")
            + "После каждого успешного действия используй его квитанцию и сразу переходи к следующему.";
        var filesBefore = new HashSet<string>(Directory.GetDirectories(Path.GetTempPath(), "troika-notepad-*"));
        var approvals = new List<string>();
        Click(window.StartButton);
        var time = Stopwatch.StartNew();
        string previous = null;
        while (!window.Execution.IsCompleted && time.Elapsed < TimeSpan.FromSeconds(145)) {
            if (window.ApproveButton.IsVisible) {
                string text = window.PendingAction;
                if (text != previous) {
                    approvals.Add(text);
                    previous = text;
                    if (stop && text.StartsWith("Сохранить", StringComparison.Ordinal)) Click(window.StopButton);
                    else Click(window.ApproveButton);
                }
            } else previous = null;
            await Task.Delay(25);
        }
        Require(window.Execution.IsCompleted, "The shared Windows Run timed out.");
        await window.Execution;
        var files = Directory.GetDirectories(Path.GetTempPath(), "troika-notepad-*").Where(path => !filesBefore.Contains(path))
            .SelectMany(path => Directory.GetFiles(path, "*.txt")).ToArray();
        Require(files.Length == 1 && approvals.Any(text => text.Contains(Expected)),
            "The shared Windows Run did not show the text and open its own file. " + window.Status.Text);
        if (stop) {
            Require(window.Status.Text == "Остановлено." && File.ReadAllBytes(files[0]).SequenceEqual(ComputerUseNotepad.FileEncoding.GetPreamble()),
                "Stop did not prevent Notepad from saving. " + window.Status.Text);
        } else {
            var expected = ComputerUseNotepad.FileEncoding.GetPreamble().Concat(Encoding.UTF8.GetBytes(Expected));
            Require((!click || approvals.Contains("Нажать ссылку «Доставка»?"))
                    && window.Status.Text.Contains(click ? "переход по ссылке" : "прокрутку") && window.Status.Text.Contains("Блокнот сохранил")
                    && File.ReadAllBytes(files[0]).SequenceEqual(expected), "The shared Windows Run could not verify both apps. " + window.Status.Text);
        }
        File.Delete(files[0]);
        Directory.Delete(Path.GetDirectoryName(files[0]), false);
        Console.WriteLine(stop ? "PASS Stop in the common window prevented Notepad save."
            : click ? "PASS One Windows Run approved and verified Notepad save and a browser section link."
            : "PASS One Windows Run approved and verified Notepad save and browser scroll.");
    }

    private static void Render(Window window, string path) {
        var image = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        image.Render(window);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(image));
        using (var file = new FileStream(path, FileMode.CreateNew, FileAccess.Write)) encoder.Save(file);
    }

    private static void Click(Button button) { button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }
    private static void Require(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
}
