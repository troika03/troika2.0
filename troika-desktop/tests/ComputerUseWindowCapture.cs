using System;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Troika.Desktop;

internal sealed class ComputerUseWindowCapture : IDisposable {
    private const int MaxWidth = 1280;
    private const int MaxHeight = 800;
    private const string TitlePrefix = "Пробное окно Тройки ";
    internal static readonly Color TargetColor = Color.FromRgb(27, 67, 112);
    private readonly Process process;
    private readonly string title;
    internal readonly IntPtr Handle;

    private ComputerUseWindowCapture(Process process, string title, IntPtr handle) {
        this.process = process;
        this.title = title;
        Handle = handle;
    }

    internal bool Visible {
        get { return !process.HasExited && FindWindow(null, title) == Handle && IsWindowVisible(Handle) && !IsIconic(Handle); }
    }

    internal static async Task<ComputerUseWindowCapture> OpenAsync(bool protectedWindow = false) {
        string id = Guid.NewGuid().ToString("N");
        string title = TitlePrefix + id;
        var start = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
            "--window-target " + id + (protectedWindow ? " protected" : "")) {
            UseShellExecute = false,
            CreateNoWindow = true
        };
        var child = Process.Start(start);
        try {
            var wait = Stopwatch.StartNew();
            while (!child.HasExited && wait.Elapsed < TimeSpan.FromSeconds(5)) {
                IntPtr window = FindWindow(null, title);
                int owner;
                if (window != IntPtr.Zero && GetWindowThreadProcessId(window, out owner) != 0 && owner == child.Id
                        && IsWindowVisible(window))
                    return new ComputerUseWindowCapture(child, title, window);
                await Task.Delay(25).ConfigureAwait(false);
            }
            throw new InvalidOperationException("The synthetic capture window did not open.");
        } catch {
            CloseChild(child);
            throw;
        }
    }

    internal Task<BitmapSource> CaptureAsync(CancellationToken cancellation) {
        return Task.Run(() => {
            if (!Visible || cancellation.IsCancellationRequested) return null;
            var pixels = new byte[MaxWidth * MaxHeight * 4];
            int width, height;
            using (var cancel = new ManualResetEvent(false))
            using (cancellation.Register(() => cancel.Set())) {
                int result = CaptureWindowFrame(Handle, process.Id, cancel.SafeWaitHandle, pixels, pixels.Length, out width, out height);
                if (result != 0 || cancellation.IsCancellationRequested || !Visible
                        || width <= 0 || width > MaxWidth || height <= 0 || height > MaxHeight)
                    return null;
            }
            var frame = BitmapSource.Create(width, height, 96, 96, PixelFormats.Pbgra32, null, pixels, width * 4);
            frame.Freeze();
            return frame;
        });
    }

    public void Dispose() { CloseChild(process); }

    private static void CloseChild(Process child) {
        using (child) {
            if (child.HasExited) return;
            try {
                if (!child.CloseMainWindow() || !child.WaitForExit(500)) {
                    child.Kill();
                    child.WaitForExit(2000);
                }
            } catch (InvalidOperationException) {
                if (!child.HasExited) throw;
            }
        }
    }

    internal static int RunTarget(string id, bool protectedWindow) {
        Guid parsed;
        if (!Guid.TryParseExact(id, "N", out parsed)) return 2;
        var app = new Application();
        var target = NewTestWindow(TitlePrefix + id, TargetColor);
        target.Content = new TextBlock {
            Text = ComputerUseExecutor.Sample,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = Brushes.White,
            FontSize = 26
        };
        if (protectedWindow) {
            target.SourceInitialized += (sender, args) => {
                if (!SetWindowDisplayAffinity(new WindowInteropHelper(target).Handle, 0x11))
                    throw new InvalidOperationException("The protected fixture could not set display affinity.");
            };
        }
        return app.Run(target);
    }

    internal static Window NewTestWindow(string title, Color color) {
        var desktop = SystemParameters.WorkArea;
        return new Window {
            Title = title,
            Width = 460,
            Height = 200,
            Left = desktop.Left + 24,
            Top = desktop.Bottom - 224,
            WindowStartupLocation = WindowStartupLocation.Manual,
            WindowStyle = WindowStyle.None,
            ResizeMode = ResizeMode.NoResize,
            ShowActivated = false,
            Background = new SolidColorBrush(color)
        };
    }

    [DllImport("TroikaWindowCapture.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory | DllImportSearchPath.System32)]
    private static extern int CaptureWindowFrame(IntPtr window, int process,
        Microsoft.Win32.SafeHandles.SafeWaitHandle cancel, [Out] byte[] pixels, int capacity, out int width, out int height);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string className, string title);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out int process);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")]
    private static extern bool SetWindowDisplayAffinity(IntPtr window, uint affinity);
}
