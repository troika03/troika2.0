using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Threading;
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

// A frame stays in preview until the user explicitly sends it in the vision lab.
internal sealed class ComputerUseVisualPreview : Window {
    private const int MaxFrameWidth = 640;
    private const int MaxFrameHeight = 240;
    private static readonly Stopwatch Clock = Stopwatch.StartNew();
    private readonly Func<TimeSpan> now;
    private readonly Func<BitmapSource, Task<string>> recognize;
    private readonly ComputerUseSession session;
    private readonly ComputerUseWindowCapture target;
    private readonly ComputerUseVisionLab vision;
    private readonly DispatcherTimer timer;
    private readonly TextBlock status;
    private CancellationTokenSource capture;
    private bool captureFailed;
    private bool frameSent;
    private TimeSpan frameExpires;
    internal readonly Button AllowButton;
    private readonly Button captureButton;
    internal readonly Button StopButton;
    internal readonly TextBox Editor;
    internal readonly Image Preview;
    internal readonly TextBlock Recognized;
    internal readonly Button SendButton;
    internal readonly TextBlock VisionAnswer;

    internal ComputerUseVisualPreview(Func<TimeSpan> now = null, Func<BitmapSource, Task<string>> recognize = null,
            ComputerUseWindowCapture target = null, ComputerUseVisionLab vision = null) {
        if (vision != null && target == null) throw new ArgumentException("The vision lab requires the separate test window.");
        this.now = now ?? (() => Clock.Elapsed);
        this.recognize = recognize ?? ReadTextAsync;
        this.target = target;
        this.vision = vision;
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
            Text = vision != null
                ? "Проверьте снимок пробного окна. Затем можно передать один кадр тестовому серверу на этом ПК."
                : target == null
                ? "Windows распознаёт текст только в пробном поле. Снимок и текст остаются на компьютере и исчезают через 15 секунд."
                : "Разрешите снимок отдельного окна «Пробное окно Тройки». Снимок и текст остаются на компьютере и исчезают через 15 секунд.",
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12)
        });
        if (target == null) {
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
        }
        var actions = new WrapPanel();
        AllowButton = AddButton(actions, "Разрешить осмотр", () => {
            if (session.Allow()) timer.Start();
            Refresh();
        });
        captureButton = AddButton(actions, "Сделать снимок", async () => await CaptureAsync());
        if (vision != null) SendButton = AddButton(actions, "Передать один кадр", async () => await SendFrameAsync());
        StopButton = AddButton(actions, "Остановить (Esc)", Stop);
        body.Children.Add(actions);
        status = new TextBlock { TextWrapping = TextWrapping.Wrap };
        body.Children.Add(status);
        Preview = new Image {
            Height = target == null ? 88 : 156,
            Stretch = Stretch.Uniform,
            StretchDirection = StretchDirection.DownOnly,
            HorizontalAlignment = HorizontalAlignment.Left
        };
        AutomationProperties.SetName(Preview, target == null ? "Снимок пробного поля" : "Снимок пробного окна");
        body.Children.Add(Preview);
        Recognized = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 0) };
        body.Children.Add(Recognized);
        if (vision != null) {
            VisionAnswer = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 0) };
            body.Children.Add(VisionAnswer);
        }
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

    private bool SourceVisible {
        get { return IsVisible && WindowState != WindowState.Minimized && (target == null ? Editor.IsVisible : target.Visible); }
    }

    internal async Task CaptureAsync() {
        Refresh();
        if (!captureButton.IsEnabled) return;
        if (VisionAnswer != null) VisionAnswer.Text = "";
        frameExpires = now().Add(TimeSpan.FromSeconds(ComputerUseExecutor.ObservationSeconds));
        Preview.Source = null;
        Recognized.Text = "";
        captureFailed = false;
        capture = new CancellationTokenSource();
        Refresh();
        try {
            var frame = target == null ? RenderField() : await target.CaptureAsync(capture.Token);
            Refresh();
            if (capture.IsCancellationRequested) return;
            if (frame == null) { captureFailed = true; return; }
            Preview.Source = frame;
            Refresh();
            string text = await recognize(frame);
            Refresh();
            if (capture.IsCancellationRequested) return;
            Recognized.Text = text == null ? "Распознавание русского текста недоступно в Windows."
                : string.IsNullOrWhiteSpace(text) ? "Текст не распознан." : "Распознанный текст: " + text;
        } catch (COMException) {
            ShowCaptureError();
        } catch (InvalidOperationException) {
            ShowCaptureError();
        } finally {
            capture.Dispose();
            capture = null;
            Refresh();
        }
    }

    internal async Task SendFrameAsync() {
        Refresh();
        if (SendButton == null || !SendButton.IsEnabled) return;
        var frame = (BitmapSource)Preview.Source;
        capture = new CancellationTokenSource();
        Refresh();
        try {
            var encoded = await Task.Run(() => ComputerUseVisionLab.Encode(frame));
            Refresh();
            if (capture.IsCancellationRequested) return;
            frameSent = true;
            VisionAnswer.Text = "Передаю кадр.";
            var answer = await vision.SendAsync(encoded, capture.Token);
            Refresh();
            if (!capture.IsCancellationRequested) VisionAnswer.Text = "Тестовый ответ: " + answer;
        } catch (OperationCanceledException) {
            ReportVisionFailure();
        } catch (HttpRequestException) {
            ReportVisionFailure();
        } catch (IOException) {
            ReportVisionFailure();
        } catch (ArgumentException) {
            ReportVisionFailure();
        } catch (InvalidOperationException) {
            ReportVisionFailure();
        } finally {
            capture.Dispose();
            capture = null;
            Refresh();
        }
    }

    private void ReportVisionFailure() {
        if (!capture.IsCancellationRequested) VisionAnswer.Text = "Не удалось получить ответ на кадр.";
    }

    private void ShowCaptureError() {
        if (capture.IsCancellationRequested) return;
        if (Preview.Source == null) captureFailed = true;
        else Recognized.Text = "Распознавание русского текста недоступно в Windows.";
    }

    private BitmapSource RenderField() {
        double width = Editor.ActualWidth;
        double height = Editor.ActualHeight;
        if (width < 1 || height < 1) return null;
        double scale = Math.Min(1, Math.Min(MaxFrameWidth / width, MaxFrameHeight / height));
        int pixelWidth = (int)Math.Ceiling(width * scale);
        int pixelHeight = (int)Math.Ceiling(height * scale);
        var visual = new DrawingVisual();
        using (var drawing = visual.RenderOpen())
            drawing.DrawRectangle(new VisualBrush(Editor), null, new Rect(0, 0, pixelWidth, pixelHeight));
        var frame = new RenderTargetBitmap(pixelWidth, pixelHeight, 96, 96, PixelFormats.Pbgra32);
        frame.Render(visual);
        return frame;
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
        bool canPreview = active && SourceVisible;
        captureButton.IsEnabled = canPreview && capture == null;
        StopButton.IsEnabled = AllowButton.IsEnabled || active;
        if (!canPreview || now() >= frameExpires) {
            if (capture != null) capture.Cancel();
            Preview.Source = null;
            Recognized.Text = "";
            if (VisionAnswer != null) VisionAnswer.Text = "";
        }
        if (SendButton != null)
            SendButton.IsEnabled = canPreview && capture == null && !frameSent && Preview.Source != null;
        Preview.Visibility = Preview.Source == null ? Visibility.Collapsed : Visibility.Visible;
        Recognized.Visibility = Recognized.Text.Length == 0 ? Visibility.Collapsed : Visibility.Visible;
        if (!active) timer.Stop();
        switch (state) {
            case ComputerUseState.Pending: status.Text = "Ожидаю разрешения."; break;
            case ComputerUseState.Active:
                status.Text = Preview.Source != null ? "Снимок готов."
                    : !canPreview ? "Пробное окно недоступно."
                    : captureFailed ? "Не удалось получить снимок." : "Осмотр разрешён.";
                break;
            case ComputerUseState.Expired: status.Text = "Срок разрешения истёк."; break;
            case ComputerUseState.Stopped: status.Text = "Осмотр остановлен."; break;
        }
    }
}
