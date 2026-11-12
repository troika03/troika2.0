using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Troika.Desktop;
using AsyncStatus = Windows.Foundation.AsyncStatus;
using Windows.Globalization;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage.Streams;

// This window runs only in the standalone test editor. Its frame stays on the
// local dispatcher and contains the field's visual tree, not desktop pixels.
internal sealed class ComputerUseVisualPreview : Window {
    private const int MaxFrameWidth = 640;
    private const int MaxFrameHeight = 240;
    private static readonly Stopwatch Clock = Stopwatch.StartNew();
    private readonly Func<TimeSpan> now;
    private readonly Func<BitmapSource, Task<string>> recognize;
    private readonly ComputerUseSession session;
    private readonly DispatcherTimer timer;
    private readonly TextBlock status;
    private bool recognizing;
    private TimeSpan frameExpires;
    internal readonly Button AllowButton;
    private readonly Button captureButton;
    internal readonly Button StopButton;
    internal readonly TextBox Editor;
    internal readonly Image Preview;
    internal readonly TextBlock Recognized;

    internal ComputerUseVisualPreview(Func<TimeSpan> now = null, Func<BitmapSource, Task<string>> recognize = null) {
        this.now = now ?? (() => Clock.Elapsed);
        this.recognize = recognize ?? ReadTextAsync;
        session = new ComputerUseSession(this.now);
        Title = "Тройка — визуальный осмотр";
        Width = 540;
        MinWidth = 380;
        SizeToContent = SizeToContent.Height;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        FontFamily = new FontFamily("Segoe UI");
        FontSize = 14;
        SetResourceReference(BackgroundProperty, SystemColors.WindowBrushKey);
        SetResourceReference(ForegroundProperty, SystemColors.WindowTextBrushKey);

        var body = new StackPanel { Margin = new Thickness(24) };
        body.Children.Add(new TextBlock {
            Text = "Windows распознаёт текст только в пробном поле. Снимок и текст остаются на компьютере и исчезают через 15 секунд.",
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12)
        });
        Editor = new TextBox {
            Text = ComputerUseExecutor.Sample,
            FontSize = 18,
            IsReadOnly = true,
            MinHeight = 64,
            Padding = new Thickness(8),
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12)
        };
        AutomationProperties.SetName(Editor, "Пробное поле");
        body.Children.Add(Editor);
        var actions = new WrapPanel();
        AllowButton = AddButton(actions, "Разрешить осмотр", () => {
            if (session.Allow()) timer.Start();
            Refresh();
        });
        captureButton = AddButton(actions, "Сделать снимок", async () => await CaptureAsync());
        StopButton = AddButton(actions, "Остановить (Esc)", Stop);
        body.Children.Add(actions);
        status = new TextBlock { TextWrapping = TextWrapping.Wrap };
        body.Children.Add(status);
        Preview = new Image {
            Height = 88,
            Stretch = Stretch.Uniform,
            StretchDirection = StretchDirection.DownOnly,
            HorizontalAlignment = HorizontalAlignment.Left
        };
        AutomationProperties.SetName(Preview, "Снимок пробного поля");
        body.Children.Add(Preview);
        Recognized = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 0) };
        body.Children.Add(Recognized);
        Content = body;

        timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        timer.Tick += (sender, args) => Refresh();
        StateChanged += (sender, args) => Refresh();
        IsVisibleChanged += (sender, args) => Refresh();
        PreviewKeyDown += (sender, args) => {
            if (args.Key != Key.Escape) return;
            args.Handled = true;
            Stop();
        };
        Closed += (sender, args) => Stop();
        Refresh();
    }

    private static Button AddButton(Panel panel, string label, Action action) {
        var button = new Button {
            Content = label,
            MinHeight = 34,
            Padding = new Thickness(12, 4, 12, 4),
            Margin = new Thickness(0, 0, 8, 10)
        };
        button.Click += (sender, args) => action();
        panel.Children.Add(button);
        return button;
    }

    private bool FieldVisible { get { return IsVisible && WindowState != WindowState.Minimized && Editor.IsVisible; } }

    internal async Task CaptureAsync() {
        Refresh();
        if (!captureButton.IsEnabled) return;
        double width = Editor.ActualWidth;
        double height = Editor.ActualHeight;
        if (width < 1 || height < 1) return;
        var takenAt = now();
        double scale = Math.Min(1, Math.Min(MaxFrameWidth / width, MaxFrameHeight / height));
        int pixelWidth = (int)Math.Ceiling(width * scale);
        int pixelHeight = (int)Math.Ceiling(height * scale);
        var visual = new DrawingVisual();
        using (var drawing = visual.RenderOpen())
            drawing.DrawRectangle(new VisualBrush(Editor), null, new Rect(0, 0, pixelWidth, pixelHeight));
        var frame = new RenderTargetBitmap(pixelWidth, pixelHeight, 96, 96, PixelFormats.Pbgra32);
        frame.Render(visual);

        frameExpires = takenAt.Add(TimeSpan.FromSeconds(ComputerUseExecutor.ObservationSeconds));
        if (session.State != ComputerUseState.Active || !FieldVisible || now() >= frameExpires) return;
        Preview.Source = frame;
        Recognized.Text = "";
        recognizing = true;
        Refresh();
        string text = null;
        try { text = await recognize(frame); }
        catch (COMException) { }
        catch (InvalidOperationException) { }
        finally {
            recognizing = false;
            Refresh();
        }
        if (Preview.Source != frame) return;
        Recognized.Text = text == null ? "Распознавание русского текста недоступно в Windows."
            : string.IsNullOrWhiteSpace(text) ? "Текст не распознан." : "Распознанный текст: " + text;
        Refresh();
    }

    internal static bool RussianOcrAvailable {
        get { return OcrEngine.IsLanguageSupported(new Language("ru")); }
    }

    private static async Task<string> ReadTextAsync(BitmapSource frame) {
        var engine = OcrEngine.TryCreateFromLanguage(new Language("ru"));
        if (engine == null) return null;
        int stride = frame.PixelWidth * 4;
        var pixels = new byte[stride * frame.PixelHeight];
        frame.CopyPixels(pixels, stride, 0);
        using (var writer = new DataWriter()) {
            writer.WriteBytes(pixels);
            using (var bitmap = SoftwareBitmap.CreateCopyFromBuffer(writer.DetachBuffer(),
                    BitmapPixelFormat.Bgra8, frame.PixelWidth, frame.PixelHeight, BitmapAlphaMode.Ignore)) {
                var completion = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
                var operation = engine.RecognizeAsync(bitmap);
                operation.Completed = (result, state) => {
                    try {
                        completion.TrySetResult(state == AsyncStatus.Completed ? result.GetResults().Text : null);
                    } catch (COMException) {
                        completion.TrySetResult(null);
                    }
                };
                return await completion.Task;
            }
        }
    }

    private void Stop() {
        session.Stop();
        Refresh();
    }

    private void Refresh() {
        var state = session.State;
        bool active = state == ComputerUseState.Active;
        AllowButton.IsEnabled = state == ComputerUseState.Pending;
        bool canPreview = active && FieldVisible;
        captureButton.IsEnabled = canPreview && !recognizing;
        StopButton.IsEnabled = AllowButton.IsEnabled || active;
        if (!canPreview || now() >= frameExpires) {
            Preview.Source = null;
            Recognized.Text = "";
        }
        Preview.Visibility = Preview.Source == null ? Visibility.Collapsed : Visibility.Visible;
        Recognized.Visibility = Recognized.Text.Length == 0 ? Visibility.Collapsed : Visibility.Visible;
        if (!active) timer.Stop();
        switch (state) {
            case ComputerUseState.Pending: status.Text = "Ожидаю разрешения."; break;
            case ComputerUseState.Active: status.Text = Preview.Source == null ? "Осмотр разрешён." : "Снимок готов."; break;
            case ComputerUseState.Expired: status.Text = "Срок разрешения истёк."; break;
            case ComputerUseState.Stopped: status.Text = "Осмотр остановлен."; break;
        }
    }
}
