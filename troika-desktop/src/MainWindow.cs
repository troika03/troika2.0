using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Windows.Shell;

namespace Troika.Desktop {
    public sealed partial class MainWindow : Window {
        private readonly ApiClient api = new ApiClient();
        private readonly LocalStore store;
        private readonly VoiceRecorder recorder = new VoiceRecorder();
        private readonly MediaPlayer player = new MediaPlayer { SpeedRatio = 1.10 };
        private PhraseSpeech replySpeech;
        private TaskCompletionSource<bool> phrasePlayback;
        private readonly DispatcherTimer recordingLimit = new DispatcherTimer { Interval = TimeSpan.FromSeconds(60) };
        private CancellationTokenSource operation;
        private TaskCompletionSource<string> pendingApproval;
        private Grid body, center, root, hero;
        private Border sidebar, inspector, inputBorder;
        private StackPanel history, transcript, panelContent;
        private ScrollViewer conversationScroll;
        private TextBox composer;
        private TextBlock status, heroTitle, heroHint, panelTitle, answer;
        private Button microphone, send, profile, stop;
        private Orb orb;
        private Grid voiceVisual;
        private string openPanel = "", audioFile = "";
        private bool busy, speaking, closed, autoSpeak = true, light, reducedMotion, preview, compact;
        private Brush background, surface, text, muted, line, accent, accentText;
        private int panelRevision;
        private readonly List<Dictionary<string, object>> sessions = new List<Dictionary<string, object>>();
        private readonly HashSet<string> sources = new HashSet<string>();
        private StackPanel sourceList;
        private double expandedWidth = 960, expandedHeight = 680;
        [DllImport("user32.dll")] private static extern bool RegisterHotKey(IntPtr hwnd, int id, uint modifiers, uint key);
        [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hwnd, int id);
        private IntPtr handle;
        private bool hotkeyRegistered;

        public MainWindow(bool designPreview) {
            preview = designPreview;
            store = preview ? new LocalStore(Path.Combine(Path.GetTempPath(), "TroikaDesktopDesign", Guid.NewGuid().ToString("N"))) : new LocalStore();
            Title = "Тройка — для Windows";
            Width = Math.Min(960, SystemParameters.WorkArea.Width * .9); Height = Math.Min(680, SystemParameters.WorkArea.Height * .9);
            MinWidth = 780; MinHeight = 540; WindowStartupLocation = WindowStartupLocation.CenterScreen;
            WindowStyle = WindowStyle.None; ResizeMode = ResizeMode.CanResize; FontFamily = BrandAssets.Font; FontSize = 14;
            var settings = store.Settings(); autoSpeak = Json.Get(settings, "auto_speak") == null || Json.Flag(settings, "auto_speak"); light = Json.Flag(settings, "light"); reducedMotion = Json.Flag(settings, "reduced_motion"); Topmost = Json.Flag(settings, "always_on_top"); interfaceAccent = Json.Text(settings, "interface_accent");
            api.Account = preview ? new AccountSession() : store.LoadSession(); api.SessionId = api.Account.HomeSession; api.SaveSession = store.SaveSession; api.PersonalProviders = new PersonalProviderStore(store.Root);
            InitializeVoiceIdentity();
            Build();
            StartReminders();
            SizeChanged += delegate { if (voiceVisual != null) { voiceVisual.Height = Math.Max(180, Math.Min(260, ActualHeight - 380)); heroTitle.FontSize = ActualHeight < 600 ? 28 : 32; if (!compact) body.ColumnDefinitions[0].Width = new GridLength(NavigationWidth); } };
            WindowChrome.SetWindowChrome(this, new WindowChrome { CaptionHeight = 0, ResizeBorderThickness = new Thickness(6), CornerRadius = new CornerRadius(14), GlassFrameThickness = new Thickness(0) });
            SourceInitialized += delegate {
                handle = new WindowInteropHelper(this).Handle;
                HwndSource.FromHwnd(handle).AddHook(WindowMessage);
                if (preview) return;
                hotkeyRegistered = RegisterHotKey(handle, 17, 0x4000 | 0x0002 | 0x0001, 0x54);
                if (!hotkeyRegistered) microphone.ToolTip = "Горячая клавиша занята. Используйте кнопку микрофона.";
            };
            Loaded += async delegate {
                if (preview) { SetStatus("Предпросмотр интерфейса", false); return; }
                await Safe(async () => {
                    using (var http = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromSeconds(12) }) { var reply = await http.GetAsync(ApiClient.Production + "/health"); SetStatus(reply.IsSuccessStatusCode ? "В сети" : "Сервис недоступен", !reply.IsSuccessStatusCode); }
                    if (api.Account.SignedIn) await RefreshAccount();
                });
            };
            recordingLimit.Tick += async delegate { recordingLimit.Stop(); await ToggleVoice(); };
            player.MediaEnded += delegate { StopPlayback(); Idle(); };
            player.MediaFailed += delegate { if (phrasePlayback != null) phrasePlayback.TrySetException(new InvalidOperationException("Не удалось воспроизвести ответ.")); StopPlayback(); SetStatus("Ответ получен. Windows не смогла воспроизвести звук.", true); Idle(); };
            PreviewKeyDown += async delegate(object sender, KeyEventArgs e) {
                if (e.Key == Key.Escape) { e.Handled = true; if (busy || recorder.Recording || speaking || localCheck != null || developmentConsent != null) await Stop(); else if (openPanel.Length > 0) ClosePanel(); else if (compact) ToggleCompact(); }
                if (e.Key == Key.N && Keyboard.Modifiers == ModifierKeys.Control) { e.Handled = true; NewConversation(); }
            };
            Closing += async delegate(object sender, System.ComponentModel.CancelEventArgs e) {
                if (closed) return;
                e.Cancel = true;
                await Stop();
                if (KeepProjectsInBackground()) return;
                closed = true; recordingLimit.Stop(); reminderTimer.Stop(); recorder.Dispose(); StopPlayback();
                DisposeProjectTray();
                DisposeAutopilotObserver();
                if (hotkeyRegistered) UnregisterHotKey(handle, 17);
                api.Dispose(); var closing = Dispatcher.BeginInvoke(new Action(Close));
            };
        }
        private IntPtr WindowMessage(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam, ref bool handled) {
            if (message == Program.ActivationMessage && !preview) {
                handled = true;
                Dispatcher.BeginInvoke(new Action(delegate { if (!IsVisible) Show(); if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal; Activate(); }));
            }
            if (message == 0x0312 && wParam.ToInt32() == 17) {
                handled = true;
                Dispatcher.BeginInvoke(new Action(async delegate {
                    if (!IsVisible) Show(); if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal; Activate();
                    if (!compact && !busy && !recorder.Recording && !speaking) ToggleCompact();
                    await ToggleVoice();
                }));
            }
            return IntPtr.Zero;
        }
        private static Brush Color(string value) { var brush = new SolidColorBrush((System.Windows.Media.Color)ColorConverter.ConvertFromString(value)); brush.Freeze(); return brush; }
        private TextBlock Label(string value, double size, Brush brush) { return new TextBlock { Text = value, FontSize = size, Foreground = brush, TextWrapping = TextWrapping.Wrap }; }
        private static void AccessibleName(DependencyObject control, string value) { AutomationProperties.SetName(control, value); }
        private double NavigationWidth { get { return (ActualWidth > 0 ? ActualWidth : Width) >= 1100 ? 256 : 192; } }
        private Button Button(string value, Action action, bool primary) {
            var button = new Button { Content = value, Tag = primary, Foreground = primary ? accentText : text, Background = primary ? accent : glass, BorderBrush = primary ? accent : line, BorderThickness = new Thickness(1), Padding = new Thickness(16, 8, 16, 8), MinHeight = 44, Margin = new Thickness(0, 0, 8, 0), Cursor = Cursors.Hand, HorizontalContentAlignment = HorizontalAlignment.Center, VerticalContentAlignment = VerticalAlignment.Center, FontSize = 14 };
            var border = new FrameworkElementFactory(typeof(Border), "outline"); border.SetValue(Border.CornerRadiusProperty, new CornerRadius(22)); border.SetBinding(Border.BackgroundProperty, new System.Windows.Data.Binding("Background") { RelativeSource = new System.Windows.Data.RelativeSource(System.Windows.Data.RelativeSourceMode.TemplatedParent) }); border.SetBinding(Border.BorderBrushProperty, new System.Windows.Data.Binding("BorderBrush") { RelativeSource = new System.Windows.Data.RelativeSource(System.Windows.Data.RelativeSourceMode.TemplatedParent) }); border.SetBinding(Border.BorderThicknessProperty, new System.Windows.Data.Binding("BorderThickness") { RelativeSource = new System.Windows.Data.RelativeSource(System.Windows.Data.RelativeSourceMode.TemplatedParent) }); border.SetBinding(Border.PaddingProperty, new System.Windows.Data.Binding("Padding") { RelativeSource = new System.Windows.Data.RelativeSource(System.Windows.Data.RelativeSourceMode.TemplatedParent) });
            var presenter = new FrameworkElementFactory(typeof(ContentPresenter)); presenter.SetBinding(ContentPresenter.HorizontalAlignmentProperty, new System.Windows.Data.Binding("HorizontalContentAlignment") { RelativeSource = new System.Windows.Data.RelativeSource(System.Windows.Data.RelativeSourceMode.TemplatedParent) }); presenter.SetValue(ContentPresenter.VerticalAlignmentProperty, VerticalAlignment.Center); border.AppendChild(presenter);
            var template = new ControlTemplate(typeof(Button)) { VisualTree = border };
            var hover = new Trigger { Property = IsMouseOverProperty, Value = true }; hover.Setters.Add(new Setter(OpacityProperty, .86, "outline")); template.Triggers.Add(hover);
            var pressed = new Trigger { Property = System.Windows.Controls.Primitives.ButtonBase.IsPressedProperty, Value = true }; pressed.Setters.Add(new Setter(OpacityProperty, .68, "outline")); template.Triggers.Add(pressed);
            var focus = new Trigger { Property = IsKeyboardFocusedProperty, Value = true }; focus.Setters.Add(new Setter(Border.BorderBrushProperty, accent, "outline")); focus.Setters.Add(new Setter(Border.BorderThicknessProperty, new Thickness(2), "outline")); template.Triggers.Add(focus);
            var disabled = new Trigger { Property = IsEnabledProperty, Value = false }; disabled.Setters.Add(new Setter(OpacityProperty, .4)); template.Triggers.Add(disabled); button.Template = template;
            button.Click += delegate { action(); }; AccessibleName(button, value); return button;
        }
        private TextBox Field(string placeholder, bool multiline) {
            var field = new TextBox { Foreground = text, Background = background, BorderBrush = line, BorderThickness = new Thickness(1), Padding = new Thickness(12), FontSize = 14, Margin = new Thickness(0, 6, 0, 16), MinHeight = multiline ? 88 : 44, AcceptsReturn = multiline, TextWrapping = TextWrapping.Wrap, VerticalContentAlignment = VerticalAlignment.Center, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, CaretBrush = accent };
            AccessibleName(field, placeholder); return field;
        }
        private void Build() {
            ApplyPalette(); navigation.Clear();
            ApplyControlStyles();
            Background = background; Foreground = text;
            var style = new Style(typeof(ScrollViewer)); style.Setters.Add(new Setter(ScrollViewer.PanningModeProperty, PanningMode.VerticalOnly)); Resources[typeof(ScrollViewer)] = style;
            Resources[SystemParameters.VerticalScrollBarWidthKey] = 6.0;
            Resources[typeof(System.Windows.Controls.Primitives.ScrollBar)] = System.Windows.Markup.XamlReader.Parse(@"<Style xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml' TargetType='{x:Type ScrollBar}'><Setter Property='Width' Value='8'/><Setter Property='Background' Value='Transparent'/><Setter Property='Template'><Setter.Value><ControlTemplate TargetType='{x:Type ScrollBar}'><Track x:Name='PART_Track' IsDirectionReversed='True' Orientation='{TemplateBinding Orientation}' Minimum='{TemplateBinding Minimum}' Maximum='{TemplateBinding Maximum}' ViewportSize='{TemplateBinding ViewportSize}' Value='{Binding Value, RelativeSource={RelativeSource TemplatedParent}, Mode=TwoWay}'><Track.Thumb><Thumb><Thumb.Template><ControlTemplate TargetType='{x:Type Thumb}'><Border Background='{DynamicResource TroikaLine}' CornerRadius='4' Margin='2,0,0,0'/></ControlTemplate></Thumb.Template></Thumb></Track.Thumb></Track></ControlTemplate></Setter.Value></Setter></Style>");
            root = new Grid { Background = background }; root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(58) }); root.RowDefinitions.Add(new RowDefinition());
            var outline = new Border { BorderBrush = line, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(14), Child = root, ClipToBounds = true }; Content = outline;
            var titlebar = new Grid { Margin = new Thickness(21, 0, 9, 0) }; titlebar.ColumnDefinitions.Add(new ColumnDefinition()); titlebar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            titlebar.MouseLeftButtonDown += delegate(object sender, MouseButtonEventArgs e) { if (e.Source is Button) return; if (e.ClickCount == 2) WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized; else if (e.LeftButton == MouseButtonState.Pressed) DragMove(); };
            var brand = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            brand.Children.Add(BrandAssets.Logo(light));
            status = Label("Подключаюсь", 11, muted); status.Margin = new Thickness(17, 5, 0, 0); status.MaxWidth = 220; status.TextTrimming = TextTrimming.CharacterEllipsis; brand.Children.Add(status); titlebar.Children.Add(brand);
            var controls = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            controls.Children.Add(Button("▱", ToggleCompact, false)); controls.Children.Add(Button("—", () => WindowState = WindowState.Minimized, false)); controls.Children.Add(Button("□", () => WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized, false)); controls.Children.Add(Button("×", Close, false));
            AccessibleName((Button)controls.Children[0], "Компактное окно"); AccessibleName((Button)controls.Children[1], "Свернуть"); AccessibleName((Button)controls.Children[2], "Развернуть"); AccessibleName((Button)controls.Children[3], "Закрыть"); Grid.SetColumn(controls, 1); titlebar.Children.Add(controls); root.Children.Add(titlebar);
            stop = Button("Стоп", () => { var task = Stop(); }, false); stop.Visibility = Visibility.Collapsed; controls.Children.Insert(0, stop);
            body = new Grid { Margin = new Thickness(12, 0, 12, 12) }; body.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(NavigationWidth) }); body.ColumnDefinitions.Add(new ColumnDefinition()); body.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(0) }); Grid.SetRow(body, 1); root.Children.Add(body);
            BuildSidebar(); BuildCenter();
            inspector = new Border { Background = background, Padding = new Thickness(24), Margin = new Thickness(10, 0, 0, 0), Visibility = Visibility.Collapsed };
            var panelGrid = new Grid(); panelGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); panelGrid.RowDefinitions.Add(new RowDefinition());
            var panelHead = new DockPanel { Margin = new Thickness(0, 0, 0, 20) }; var close = Button("×", ClosePanel, false); close.Margin = new Thickness(0); DockPanel.SetDock(close, Dock.Right); AccessibleName(close, "Закрыть панель"); panelHead.Children.Add(close); panelTitle = Label("", 21, text); panelTitle.VerticalAlignment = VerticalAlignment.Center; panelHead.Children.Add(panelTitle); panelGrid.Children.Add(panelHead);
            panelContent = new StackPanel(); var scroller = new ScrollViewer { Content = panelContent, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }; Grid.SetRow(scroller, 1); panelGrid.Children.Add(scroller); inspector.Child = panelGrid; Grid.SetColumn(inspector, 2); body.Children.Add(inspector);
            if (compact) ApplyCompact();
            UpdateNavigation(); if (preview) SetStatus("Предпросмотр", false);
        }
        private void BuildSidebar() {
            sidebar = new Border { Background = navigationSurface, CornerRadius = new CornerRadius(12), Padding = new Thickness(8, 16, 8, 12), Margin = new Thickness(0, 0, 10, 0) };
            var grid = new Grid(); grid.RowDefinitions.Add(new RowDefinition()); grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); sidebar.Child = grid;
            var top = new StackPanel();
            top.Children.Add(NavigationButton("Главная", "home", "")); top.Children.Add(NavigationButton("Разговоры", "history", "Разговоры"));
            top.Children.Add(NavigationButton("Дела", "tasks", "Дела")); top.Children.Add(NavigationButton("Файлы", "files", "Файлы"));
            top.Children.Add(NavigationButton("Разработка", "code", "Разработка")); top.Children.Add(NavigationButton("Память", "memory", "Память")); top.Children.Add(NavigationButton("Возможности", "spark", "Возможности"));
            var create = Button("+  Новый разговор", NewConversation, false); create.FontSize = 12; create.Padding = new Thickness(8); create.Margin = new Thickness(4, 16, 4, 16); top.Children.Add(create); var recent = Label("Недавнее", 12, muted); recent.Margin = new Thickness(12, 0, 0, 0); top.Children.Add(recent);
            history = new StackPanel { Margin = new Thickness(8, 12, 8, 12) }; top.Children.Add(history); var scroll = new ScrollViewer { Content = top, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }; grid.Children.Add(scroll); RenderHistory();
            var bottom = new StackPanel(); bottom.Children.Add(NavigationButton("Настройки", "profile", "Аккаунт"));
            // Authentication status remains separate from the persistent profile destination.
            profile = Button(api.Account.SignedIn ? "Аккаунт" : "Войти", () => OpenPanel("Аккаунт"), false); profile.Visibility = Visibility.Collapsed; bottom.Children.Add(profile); Grid.SetRow(bottom, 1); grid.Children.Add(bottom); body.Children.Add(sidebar);
        }
        private void BuildCenter() {
            center = new Grid { Margin = new Thickness(13, 0, 3, 0), MaxWidth = 820 }; center.RowDefinitions.Add(new RowDefinition { Height = new GridLength(16) }); center.RowDefinitions.Add(new RowDefinition()); center.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            Grid.SetColumn(center, 1); body.Children.Add(center);
            var work = new Grid(); Grid.SetRow(work, 1); center.Children.Add(work);
            hero = new Grid { VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 10) }; hero.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); hero.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); hero.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); hero.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var visual = new Grid { Width = 260, Height = 260, HorizontalAlignment = HorizontalAlignment.Center };
            voiceVisual = visual; visual.Height = Math.Max(180, Math.Min(260, Height - 380));
            orb = new Orb { LightTheme = light, Motion = !reducedMotion && SystemParameters.ClientAreaAnimation }; visual.Children.Add(orb);
            var orbButton = Button("", () => { var task = ToggleVoice(); }, false); orbButton.Background = Brushes.Transparent; orbButton.BorderThickness = new Thickness(0); orbButton.Margin = new Thickness(0); orbButton.HorizontalAlignment = HorizontalAlignment.Stretch; orbButton.VerticalAlignment = VerticalAlignment.Stretch; orbButton.ToolTip = "Нажмите и скажите задачу"; AccessibleName(orbButton, "Начать или остановить голосовой запрос"); visual.Children.Add(orbButton); Grid.SetRow(visual, 2); hero.Children.Add(visual);
            heroTitle = Label("Чем помочь?", Height < 600 ? 28 : 32, text); heroTitle.FontWeight = FontWeights.Medium; heroTitle.HorizontalAlignment = HorizontalAlignment.Center; heroTitle.Margin = new Thickness(0, 0, 0, 12); Grid.SetRow(heroTitle, 0); hero.Children.Add(heroTitle);
            heroHint = Label("Нажмите на микрофон", 14, muted); heroHint.HorizontalAlignment = HorizontalAlignment.Center; heroHint.TextAlignment = TextAlignment.Center; Grid.SetRow(heroHint, 1); hero.Children.Add(heroHint);
            var shortcuts = new WrapPanel { HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 21, 0, 0), MaxWidth = 490 };
            shortcuts.Children.Add(Button("Файлы", () => OpenPanel("Файлы"), false)); shortcuts.Children.Add(Button("Дела", () => OpenPanel("Дела"), false)); shortcuts.Children.Add(Button("Разработка", () => OpenPanel("Разработка"), false)); Grid.SetRow(shortcuts, 3); hero.Children.Add(shortcuts); work.Children.Add(hero);
            transcript = new StackPanel { Margin = new Thickness(5, 15, 12, 12) }; conversationScroll = new ScrollViewer { Content = transcript, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Visibility = Visibility.Collapsed }; work.Children.Add(conversationScroll);
            var bottom = new StackPanel { Margin = new Thickness(0, 10, 0, 0) };
            inputBorder = new Border { Background = glass, BorderBrush = line, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(26), Padding = new Thickness(16, 12, 12, 12) };
            var input = new Grid(); input.ColumnDefinitions.Add(new ColumnDefinition()); input.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); input.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            composer = new TextBox { Background = Brushes.Transparent, Foreground = text, CaretBrush = accent, BorderThickness = new Thickness(0), FontSize = 15, MinHeight = 32, MaxHeight = 86, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, VerticalContentAlignment = VerticalAlignment.Center, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, ToolTip = "Напишите задачу. Enter — отправить, Shift+Enter — новая строка." }; AccessibleName(composer, "Текст задачи");
            composer.PreviewKeyDown += async delegate(object sender, KeyEventArgs e) { if (e.Key == Key.Enter && Keyboard.Modifiers != ModifierKeys.Shift) { e.Handled = true; await Send(); } }; input.Children.Add(composer);
            composer.GotKeyboardFocus += delegate { inputBorder.BorderBrush = accent; }; composer.LostKeyboardFocus += delegate { inputBorder.BorderBrush = line; };
            var placeholder = Label("Напишите задачу…", 14, muted); placeholder.IsHitTestVisible = false; placeholder.Margin = new Thickness(4, 0, 0, 0); placeholder.VerticalAlignment = VerticalAlignment.Center; input.Children.Add(placeholder);
            composer.TextChanged += delegate { placeholder.Visibility = composer.Text.Length == 0 ? Visibility.Visible : Visibility.Collapsed; };
            microphone = Button("Говорить", () => { var task = ToggleVoice(); }, true); microphone.Margin = new Thickness(10, 0, 6, 0); microphone.MinWidth = 93; microphone.ToolTip = "Ctrl+Alt+T — голос. Повторное нажатие остановит запись или ответ."; Grid.SetColumn(microphone, 1); input.Children.Add(microphone);
            send = Button("↑", () => { var task = Send(); }, false); send.FontSize = 20; send.Padding = new Thickness(13, 4, 13, 4); send.Margin = new Thickness(0); AccessibleName(send, "Отправить задачу"); Grid.SetColumn(send, 2); input.Children.Add(send); inputBorder.Child = input; bottom.Children.Add(inputBorder);
            Grid.SetRow(bottom, 2); center.Children.Add(bottom);
        }
        private void RenderHistory() {
            history.Children.Clear();
            if (sessions.Count == 0) { history.Children.Add(Label(api.Account.SignedIn ? "Пока нет разговоров" : "Войдите для истории", 12, muted)); return; }
            foreach (var item in sessions.Take(30)) {
                var id = Json.Text(item, "id"); var title = Json.Text(item, "title"); if (title.Length == 0) title = Json.Text(item, "preview"); if (title.Length == 0) title = "Разговор";
                if (title.Length > 56) title = title.Substring(0, 56) + "…";
                var button = Button(title, () => { var task = LoadConversation(id); }, false); button.Content = Label(title, 12, text); button.ToolTip = title; button.Margin = new Thickness(0, 0, 0, 8); button.BorderThickness = new Thickness(0); button.Background = id == api.SessionId ? tint : Brushes.Transparent; button.HorizontalContentAlignment = HorizontalAlignment.Left; history.Children.Add(button);
            }
        }
        private void SetStatus(string value, bool error) { status.Text = value; status.Foreground = error ? Color(light ? "#A84632" : "#F0A994") : muted; status.ToolTip = value; UpdateStop(); }
        private void UpdateStop() { if (stop != null) stop.Visibility = busy || recorder.Recording || speaking || localCheck != null ? Visibility.Visible : Visibility.Collapsed; }
        private void Idle() { orb.SetState("idle"); microphone.Content = "Говорить"; send.IsEnabled = !busy; UpdateStop(); if (hero.Visibility == Visibility.Visible) { heroTitle.Text = "Чем помочь?"; heroHint.Text = "Нажмите на микрофон"; } }
        private async Task Safe(Func<Task> work) {
            try { await work(); }
            catch (OperationCanceledException) { if (!closed) SetStatus("Остановлено", false); }
            catch (ApiException error) { if (!closed) { SetStatus(error.Message, true); if (error.Status == 401 || error.Status == 403) { CancelVoiceEnrollment(); InvalidateVoiceIdentity(); recordingLimit.Stop(); recorder.Dispose(); store.ForgetSession(); api.Account = new AccountSession(); api.SessionId = ""; sessions.Clear(); transcript.Children.Clear(); ShowHero(); RenderHistory(); profile.Content = "Войти"; if (openPanel == "Аккаунт") { var pending = Dispatcher.BeginInvoke(new Action(() => OpenPanel("Аккаунт"))); } } } }
            catch (Exception error) { if (!closed) SetStatus(error is System.Net.Http.HttpRequestException ? "Нет соединения. Проверьте интернет и повторите." : error.Message, true); }
        }
        private void ShowHero() { hero.Visibility = Visibility.Visible; conversationScroll.Visibility = Visibility.Collapsed; UpdateNavigation(); }
        private void ShowConversation() { hero.Visibility = Visibility.Collapsed; conversationScroll.Visibility = Visibility.Visible; UpdateNavigation(); }
        private void ShowHome() {
            ClosePanel(); ShowHero();
            if (!busy && !recorder.Recording && !speaking) Idle();
        }
        private void ContinueConversation() { ClosePanel(); ShowConversation(); }
        private TextBlock AddMessage(string role, string content) {
            ShowConversation();
            var block = new StackPanel { Margin = new Thickness(0, 0, 0, 24) };
            var label = Label(role == "user" ? "Вы" : "Тройка", 11, role == "user" ? muted : accent); label.FontWeight = FontWeights.SemiBold; label.Margin = new Thickness(0, 0, 0, 7); block.Children.Add(label);
            var message = new TextBlock { Foreground = text, FontSize = 16, TextWrapping = TextWrapping.Wrap, LineHeight = 25, Text = content }; block.Children.Add(message);
            var copy = Button("Копировать", () => { if (message.Text.Length > 0) Clipboard.SetText(message.Text); }, false); copy.BorderThickness = new Thickness(0); copy.Foreground = muted; copy.HorizontalAlignment = HorizontalAlignment.Left; copy.Padding = new Thickness(0, 6, 8, 0); copy.FontSize = 10; block.Children.Add(copy); transcript.Children.Add(block); conversationScroll.ScrollToEnd(); return message;
        }
        private void NewConversation() {
            if (busy || recorder.Recording || speaking) { SetStatus("Сначала остановите текущую задачу.", true); return; }
            api.SessionId = "desktop-" + Guid.NewGuid().ToString("N"); transcript.Children.Clear(); ShowHero(); ClosePanel(); composer.Clear(); Idle(); RenderHistory();
        }
        private async Task LoadConversation(string id) {
            if (busy || recorder.Recording || speaking) { SetStatus("Сначала остановите текущую задачу.", true); return; }
            int revision = panelRevision; string owner = api.Account.Email, device = api.Account.DeviceId, session = api.SessionId;
            await Safe(async () => {
                var value = await api.Get("/v1/sessions/" + Uri.EscapeDataString(id) + "/messages?limit=60", CancellationToken.None);
                if (closed || revision != panelRevision || owner != api.Account.Email || device.Length > 0 && device != api.Account.DeviceId || session != api.SessionId || busy || recorder.Recording || speaking) return;
                api.SessionId = id; transcript.Children.Clear(); ShowHero();
                foreach (var message in Json.Rows(value, "messages")) { var role = Json.Text(message, "role"); if (role == "user" || role == "assistant") { var content = Json.Content(Json.Get(message, "content")); content = System.Text.RegularExpressions.Regex.Replace(content, @"^\[сейчас [^\]]*\]\s*", ""); if (content.Length > 0) AddMessage(role, content); } }
                ContinueConversation(); RenderHistory(); SetStatus("История загружена", false);
            });
        }
        private async Task RefreshAccount() {
            ObserveAutopilot();
            var value = await api.Get("/v1/sessions?limit=30", CancellationToken.None); sessions.Clear(); sessions.AddRange(Json.Rows(value, "sessions")); RenderHistory(); profile.Content = "Аккаунт";
            await ReceiveFiles();
        }
        private async Task Send() {
            if (projectSpeech != null) projectSpeech.Cancel();
            if (busy || recorder.Recording || localCheck != null || developmentRelay != null && developmentRelay.Checking) return;
            StopPlayback(); var input = composer.Text.Trim(); if (input.Length == 0) { composer.Focus(); return; }
            try { var local = TryLocalAction(input); if (local != null) { composer.Clear(); AddMessage("user", input); AddMessage("assistant", local); SetStatus("Готово на этом ПК", false); return; } } catch (Exception error) { SetStatus(error.Message, true); return; }
            if (!api.Account.SignedIn) { await OpenPanelTask("Аккаунт"); SetStatus("Войдите, чтобы отправить задачу.", false); return; }
            composer.Clear(); AddMessage("user", input); answer = AddMessage("assistant", ""); sourceList = new StackPanel(); sources.Clear(); transcript.Children.Add(sourceList);
            busy = true; send.IsEnabled = false; microphone.Content = "Стоп"; operation = new CancellationTokenSource(TimeSpan.FromMinutes(10)); var cancellation = operation.Token; SetStatus("Разбираюсь…", false); orb.SetState("thinking");
            await Safe(async () => {
                var speechText = new System.Text.StringBuilder();
                var speechOwner = api.Account.Email;
                replySpeech = autoSpeak ? new PhraseSpeech(api.Speech, async (bytes, token) => {
                    if (api.Account.Email != speechOwner || !api.Account.SignedIn) throw new OperationCanceledException();
                    await PlayPhrase(bytes, token);
                }, cancellation) : null;
                var result = await api.Run(input, ev => {
                    if (closed) return;
                    var kind = Json.Text(ev, "event");
                    if (kind == "message.delta") { var delta = Json.Text(ev, "delta"); answer.Text += delta; speechText.Append(delta); if (replySpeech != null) replySpeech.Add(delta); conversationScroll.ScrollToEnd(); }
                    if (kind == "tool.started") { SetStatus(ToolStatus(Json.Text(ev, "tool")), false); orb.SetState("acting"); }
                    RenderSources(Json.Map(Json.Get(ev, "web_activity")), sourceList, sources);
                }, AskApproval, cancellation);
                answer.Text = result; await ReceiveFiles(); SetStatus("Готово", false);
                if (replySpeech != null) {
                    if (speechText.Length == 0) replySpeech.Add(result);
                    try { await replySpeech.Finish(); } catch (OperationCanceledException) { } catch { SetStatus("Ответ получен. Голос сейчас недоступен.", true); }
                }
            });
            if (replySpeech != null) { replySpeech.Dispose(); replySpeech = null; }
            if (api.ActiveRun.Length > 0) {
                using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(12))) {
                    try { await api.Stop(deadline.Token); } catch { SetStatus("Ответ не завершён. Сервер не подтвердил остановку; проверьте историю.", true); }
                }
            }
            busy = false; operation.Dispose(); operation = null; if (!speaking) Idle(); send.IsEnabled = true;
            if (!closed && api.Account.SignedIn) await Safe(async () => { var value = await api.Get("/v1/sessions?limit=30", CancellationToken.None); sessions.Clear(); sessions.AddRange(Json.Rows(value, "sessions")); RenderHistory(); });
        }
        private static string ToolStatus(string tool) { if (tool.Contains("search") || tool.Contains("research")) return "Ищу источники…"; if (tool.Contains("document") || tool.Contains("presentation")) return "Создаю файл…"; if (tool.Contains("assistant") || tool.Contains("remind")) return "Обновляю дела…"; return "Выполняю задачу…"; }
        private async Task ToggleVoice() {
            if (voiceEnrollment) { await ToggleVoiceEnrollment(); return; }
            if (projectSpeech != null) {
                projectSpeech.Cancel();
                var report = Autopilot.NextReport(true); if (report != null) Autopilot.ReportSpoken(report);
            }
            await Safe(async () => {
                if (busy) { await Stop(); return; }
                if (speaking) { StopPlayback(); Idle(); return; }
                if (!api.Account.SignedIn) { await OpenPanelTask("Аккаунт"); SetStatus("Для голоса войдите в аккаунт.", false); return; }
                if (!recorder.Recording) {
                    voiceRecordingOwner = api.Account.Email; voiceRecordingEpoch = voiceIdentityEpoch;
                    recorder.Start(); recordingLimit.Start(); microphone.Content = "Отправить"; send.IsEnabled = false; orb.SetState("listening"); heroTitle.Text = "Слушаю"; heroHint.Text = "Нажмите ещё раз, когда закончите. До 60 секунд."; SetStatus("Микрофон включён", false); return;
                }
                recordingLimit.Stop(); var audio = recorder.Stop();
                if (audio.Length < 3244) { Array.Clear(audio, 0, audio.Length); Idle(); SetStatus("Запись слишком короткая. Повторите задачу.", true); return; }
                string owner = voiceRecordingOwner; int epoch = voiceRecordingEpoch;
                var active = new CancellationTokenSource(TimeSpan.FromSeconds(95)); operation = active;
                busy = true; voiceProcessing = true; microphone.Content = "Стоп"; orb.SetState("thinking"); SetStatus(voiceIdentities.Load(owner).Enabled ? "Проверяю голос на этом ПК…" : "Распознаю речь…", false);
                try { composer.Text = await voiceRequestGate.Transcribe(audio, owner, () => VoiceIdentityCurrent(owner, epoch), api.Transcribe, active.Token); }
                finally { Array.Clear(audio, 0, audio.Length); voiceProcessing = false; active.Dispose(); if (operation == active) { busy = false; operation = null; Idle(); } }
                if (!VoiceIdentityCurrent(owner, epoch)) return;
                if (composer.Text.Trim().Length == 0) { SetStatus("Речь не распознана. Повторите или напишите задачу.", true); return; }
                await Send();
            });
        }
        private async Task Speak(string value, CancellationToken cancellation) {
            SetStatus("Готово · озвучиваю", false); var bytes = await api.Speech(value.Length > 10000 ? value.Substring(0, 10000) : value, cancellation); cancellation.ThrowIfCancellationRequested();
            StopPlayback(); var folder = Path.Combine(store.Root, "audio"); Directory.CreateDirectory(folder); audioFile = Path.Combine(folder, Guid.NewGuid().ToString("N") + ".mp3"); File.WriteAllBytes(audioFile, bytes); Array.Clear(bytes, 0, bytes.Length);
            speaking = true; player.Open(new Uri(audioFile)); player.Play(); orb.SetState("speaking"); microphone.Content = "Прервать";
        }
        private async Task PlayPhrase(byte[] bytes, CancellationToken cancellation) {
            cancellation.ThrowIfCancellationRequested(); StopPlayback();
            var folder = Path.Combine(store.Root, "audio"); Directory.CreateDirectory(folder);
            audioFile = Path.Combine(folder, Guid.NewGuid().ToString("N") + ".mp3"); File.WriteAllBytes(audioFile, bytes);
            var done = new TaskCompletionSource<bool>(); phrasePlayback = done;
            using (cancellation.Register(() => Dispatcher.BeginInvoke(new Action(() => { done.TrySetCanceled(); StopPlayback(); })))) {
                speaking = true; player.Open(new Uri(audioFile)); player.Play(); orb.SetState("speaking"); microphone.Content = "Прервать";
                var deadline = Task.Delay(TimeSpan.FromSeconds(90), cancellation);
                if (await Task.WhenAny(done.Task, deadline) != done.Task) { StopPlayback(); cancellation.ThrowIfCancellationRequested(); throw new TimeoutException(); }
                await done.Task;
            }
        }
        private void StopPlayback() { player.Stop(); player.Close(); speaking = false; if (audioFile.Length > 0) { try { File.Delete(audioFile); } catch { } audioFile = ""; } var done = phrasePlayback; phrasePlayback = null; if (done != null) done.TrySetResult(true); }
        private async Task Stop() {
            InvalidateVoiceIdentity();
            if (replySpeech != null) replySpeech.Cancel();
            if (projectSpeech != null) projectSpeech.Cancel();
            if (localCheck != null) localCheck.Cancel();
            if (developmentConsent != null) developmentConsent.TrySetResult(false);
            if (developmentRelay != null) await developmentRelay.Disable();
            recordingLimit.Stop(); recorder.Dispose(); StopPlayback(); if (localCheck != null) localCheck.Cancel(); if (pendingApproval != null) pendingApproval.TrySetResult("deny");
            var active = operation;
            if (active != null) {
                using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(12))) {
                    // Start Stop with its own deadline before cancelling the event reader.
                    var stopping = api.Stop(deadline.Token); active.Cancel();
                    try { await stopping; SetStatus("Остановлено", false); } catch { SetStatus("Соединение остановлено. Сервер не подтвердил остановку; проверьте историю.", true); }
                }
            } else SetStatus("Остановлено", false);
            Idle();
        }
        private async Task<string> AskApproval(Dictionary<string, object> request) {
            pendingApproval = new TaskCompletionSource<string>(); await OpenPanelTask("Подтверждение"); panelContent.Children.Clear();
            panelContent.Children.Add(Label(Json.Text(request, "description"), 15, text)); Gap();
            var allowed = Json.Get(request, "choices") as System.Collections.IEnumerable; bool once = false; if (allowed != null) foreach (var choice in allowed) if (Convert.ToString(choice) == "once") once = true;
            if (once) AddPanelButton("Разрешить один раз", () => pendingApproval.TrySetResult("once"), true);
            AddPanelButton("Отмена", () => pendingApproval.TrySetResult("deny"), false);
            var result = await pendingApproval.Task; pendingApproval = null; ClosePanel(); return result;
        }
        private async Task ReceiveFiles() {
            var pending = await api.Get("/v1/device-files", CancellationToken.None);
            foreach (var file in Json.Rows(pending, "data")) {
                await Safe(async () => { var path = await store.Receive(api, file, CancellationToken.None); var button = Button("Открыть " + Path.GetFileName(path), () => OpenFile(path), true); button.HorizontalAlignment = HorizontalAlignment.Left; button.Margin = new Thickness(0, 0, 0, 10); transcript.Children.Add(button); });
            }
        }
        private async void OpenPanel(string title) { await OpenPanelTask(title); }
        private async Task OpenPanelTask(string title) {
            if (title != "Мой голос") CancelVoiceEnrollment();
            if (title == "Каталог возможностей") title = "Возможности";
            if (pendingApproval != null && title != "Подтверждение") return;
            if (title != "Разработка" && developmentRelay != null && developmentRelay.Enabled) await developmentRelay.Disable();
            if (compact) { compact = false; MinWidth = 780; MinHeight = 540; Width = Math.Max(780, expandedWidth); Height = Math.Max(540, expandedHeight); ApplyCompact(); }
            openPanel = title; panelRevision++; int revision = panelRevision;
            panelTitle.Text = title == "Аккаунт" ? "Настройки" : title; panelContent.Children.Clear(); panelContent.Children.Add(Label("Загружаю…", 13, muted)); inspector.Visibility = Visibility.Visible;
            center.Visibility = Visibility.Collapsed; sidebar.Visibility = Visibility.Visible; body.ColumnDefinitions[0].Width = new GridLength(NavigationWidth); body.ColumnDefinitions[2].Width = new GridLength(0); Grid.SetColumn(inspector, 1); Grid.SetColumnSpan(inspector, 2); UpdateNavigation();
            await Safe(async () => {
                if (title == "Разговоры") { await RenderConversations(); return; }
                if (title == "Возможности") { await LoadCapabilityCatalogue(); return; }
                if (title == "Действия на ПК") { RenderCapabilities(); return; }
                if (title == "Разработка") { RenderDevelopment(); return; }
                if (title == "Аккаунт") { await RenderAccount(); return; }
                if (title == "Мой голос") { RenderVoiceIdentity(); return; }
                if (title == "Файлы") { await RenderFiles(); return; }
                if (title == "Подтверждение") return;
                if (!api.Account.SignedIn) { panelContent.Children.Clear(); panelContent.Children.Add(Label("Войдите, чтобы увидеть " + title.ToLowerInvariant() + ".", 14, muted)); AddPanelButton("Войти", () => OpenPanel("Аккаунт"), true); SurfaceGroup(0, "Ваши " + title.ToLowerInvariant(), "Раздел доступен на телефоне и ПК в одном аккаунте.", title == "Дела" ? "tasks" : "memory"); return; }
                var value = await api.Get(title == "Дела" ? "/v1/assistant/tasks?include_closed=false" : "/v1/memories", CancellationToken.None);
                if (revision != panelRevision) return; panelContent.Children.Clear();
                if (title == "Дела") { var projects = await api.Get("/v1/assistant/projects", CancellationToken.None); if (revision != panelRevision) return; RenderTasks(value, projects); } else RenderMemories(value);
            });
        }
        private void ClosePanel() {
            CancelVoiceEnrollment();
            if (developmentConsent != null) developmentConsent.TrySetResult(false);
            if (developmentRelay != null && developmentRelay.Enabled) { var task = developmentRelay.Disable(); }
            if (pendingApproval != null) pendingApproval.TrySetResult("deny");
            openPanel = ""; panelRevision++; inspector.Visibility = Visibility.Collapsed; body.ColumnDefinitions[2].Width = new GridLength(0);
            center.Visibility = Visibility.Visible; Grid.SetColumn(inspector, 2); Grid.SetColumnSpan(inspector, 1); UpdateNavigation();
            if (!compact) { sidebar.Visibility = Visibility.Visible; body.ColumnDefinitions[0].Width = new GridLength(NavigationWidth); }
        }
        private void Gap() { panelContent.Children.Add(new Border { Height = 15 }); }
        private async Task RenderConversations() {
            panelContent.Children.Clear();
            if (transcript.Children.Count > 0) AddPanelButton("Продолжить разговор", ContinueConversation, false);
            if (!api.Account.SignedIn) {
                panelContent.Children.Add(Label("Войдите, чтобы открыть разговоры.", 14, muted));
                AddPanelButton("Войти", () => OpenPanel("Аккаунт"), true); return;
            }
            int revision = panelRevision; string owner = api.Account.Email;
            panelContent.Children.Add(Label("Загружаю…", 14, muted));
            var value = await api.Get("/v1/sessions?limit=30", CancellationToken.None);
            if (revision != panelRevision || api.Account.Email != owner || !api.Account.SignedIn) return;
            sessions.Clear(); sessions.AddRange(Json.Rows(value, "sessions")); RenderHistory(); panelContent.Children.Clear();
            if (transcript.Children.Count > 0) AddPanelButton("Продолжить разговор", ContinueConversation, false);
            if (sessions.Count == 0) EmptyState("Пока нет разговоров", "Начните с новой задачи.", "history");
            foreach (var item in sessions) {
                string id = Json.Text(item, "id"), title = Json.Text(item, "title");
                if (title.Length == 0) title = Json.Text(item, "preview"); if (title.Length == 0) title = "Разговор";
                var row = Button(title, () => { var task = LoadConversation(id); }, false);
                row.Content = new TextBlock { Text = title, Foreground = text, TextTrimming = TextTrimming.CharacterEllipsis, TextWrapping = TextWrapping.NoWrap };
                row.HorizontalContentAlignment = HorizontalAlignment.Left; row.Padding = new Thickness(16, 12, 16, 12); row.Margin = new Thickness(0, 0, 0, 8); panelContent.Children.Add(row);
            }
            AddPanelButton("Новый разговор", NewConversation, true);
        }
        private void AddPanelButton(string title, Action action, bool primary) { var button = Button(title, action, primary); button.Margin = new Thickness(0, 6, 0, 4); button.HorizontalAlignment = HorizontalAlignment.Left; button.MaxWidth = 320; button.Content = Label(title, 14, primary ? accentText : text); panelContent.Children.Add(button); }
        private async Task RenderAccount() {
            panelContent.Children.Clear();
            if (!api.Account.SignedIn) {
                int signIn = panelContent.Children.Count;
                panelContent.Children.Add(Label("Почта", 12, muted)); var email = Field("Почта", false); panelContent.Children.Add(email);
                panelContent.Children.Add(Label("Пароль", 12, muted)); var password = new PasswordBox { Background = background, Foreground = text, BorderBrush = line, Padding = new Thickness(12), Margin = new Thickness(0, 6, 0, 16) }; AccessibleName(password, "Пароль"); panelContent.Children.Add(password);
                var resultLabel = Label("", 12, muted); bool authenticating = false;
                Action<bool> login = async register => {
                    if (authenticating || busy) return;
                    authenticating = true; resultLabel.Text = "Подключаюсь…";
                    try { if (email.Text.Trim().Length == 0 || password.Password.Length == 0) throw new InvalidOperationException("Введите почту и пароль.");
                        await api.Authenticate(email.Text, password.Password, register, CancellationToken.None); password.Clear(); await RefreshAccount(); await RenderAccount(); SetStatus("Вы вошли в аккаунт", false);
                    } catch (Exception error) { resultLabel.Text = error is System.Net.Http.HttpRequestException ? "Нет соединения с сервером." : error.Message; } finally { authenticating = false; }
                };
                int actions = panelContent.Children.Count; AddPanelButton("Войти", () => login(false), true); AddPanelButton("Создать аккаунт", () => login(true), false); CompactActions(actions); panelContent.Children.Add(resultLabel);
                panelContent.Children.Add(Label("Новый пароль: от 10 символов.", 12, muted)); SurfaceGroup(signIn, "Вход", "Один аккаунт для телефона и ПК.", "profile"); AddAppearanceSettings(); AddPanelButton("Действия на ПК", () => OpenPanel("Действия на ПК"), false); return;
            }
            int revision = panelRevision; var subscription = await api.Get("/v1/subscription", CancellationToken.None); if (revision != panelRevision) return;
            RenderAccountDetails(api.Account.Email, subscription);
        }
        private void RenderAccountDetails(string email, Dictionary<string, object> subscription) {
            int account = panelContent.Children.Count; panelContent.Children.Add(Label(email, 14, muted)); Gap();
            var plan = Json.Text(subscription, "plan"); panelContent.Children.Add(Label(plan.Length == 0 ? "Тариф недоступен" : char.ToUpper(plan[0]) + plan.Substring(1), 24, text));
            if (Json.Flag(subscription, "resource_enforced")) {
                panelContent.Children.Add(Label("Осталось " + Json.Text(subscription, "remaining") + " расчётных AI-токенов", 13, muted));
                panelContent.Children.Add(Label("Использовано: " + Json.Text(subscription, "spent") + " · В резерве: " + Json.Text(subscription, "reserved"), 12, muted));
                DateTime resets; if (DateTime.TryParse(Json.Text(subscription, "resets_at"), out resets)) panelContent.Children.Add(Label("Обновление: " + resets.ToLocalTime().ToString("d MMM, HH:mm"), 12, muted));
                panelContent.Children.Add(Label("Контекст, история, ответ и облачный голос входят в общий ресурс. Локальные команды бесплатны.", 12, muted));
                AddPanelButton("Расход последних операций", () => ShowResourceDetails(subscription), false);
            } else panelContent.Children.Add(Label("Месячный учёт AI-токенов ещё не включён. Баланс появится после подключения всех расходов.", 12, muted));
            if (Json.Flag(subscription, "byok_enabled")) AddPanelButton("Свой API-ключ", ShowOwnApi, false);
            AddBillingOptions(Json.Flag(subscription, "billing_enabled") && !Json.Flag(subscription, "billing_test"), Json.Flag(subscription, "verification_enabled"));
            SurfaceGroup(account, "Аккаунт и тариф", "", "profile"); int settings = panelContent.Children.Count;
            Check("Озвучивать ответы", autoSpeak, value => { autoSpeak = value; SaveSettings(); }); Check("Закрепить поверх окон", Topmost, value => { Topmost = value; SaveSettings(); }); Check("Меньше анимации", reducedMotion, value => { reducedMotion = value; orb.Motion = !value && SystemParameters.ClientAreaAnimation; orb.SetState(orb.State); SaveSettings(); });
            AddPanelButton("Мой голос", () => OpenPanel("Мой голос"), false);
            SurfaceGroup(settings, "На этом компьютере", "Голос и поведение окна", "home"); AddAppearanceSettings();
            int management = panelContent.Children.Count;
            AddPanelButton("Устройства", () => { var task = ShowDevices(); }, false);
            AddPanelButton("Действия на ПК", () => OpenPanel("Действия на ПК"), false);
            AddPanelButton("Напоминания и тихие часы", () => { var task = ShowNotifications(); }, false);
            AddPanelButton("Экспорт данных аккаунта…", () => { var task = ExportAccount(); }, false);
            CompactActions(management); SurfaceGroup(management, "Устройства и данные", "", "files"); int access = panelContent.Children.Count;
            AddPanelButton("Выйти на этом ПК", () => { var task = Logout(); }, false);
            AddPanelButton("Удалить аккаунт…", ConfirmAccountDeletion, false);
            CompactActions(access); SurfaceGroup(access, "Доступ к аккаунту", "Удаление аккаунта требует отдельного подтверждения.", "profile");
            panelContent.Children.Add(Label("Ctrl+Alt+T — голос. Готовые файлы хранятся на этом ПК; автоматической облачной копии нет.", 11, muted));
        }
        private void Check(string title, bool current, Action<bool> update) { var check = new CheckBox { Content = title, IsChecked = current, Foreground = text, FontSize = 13, Margin = new Thickness(0, 7, 0, 7) }; check.Click += delegate { update(check.IsChecked == true); }; panelContent.Children.Add(check); }
        private void SaveSettings() { store.SaveSettings(new { auto_speak = autoSpeak, light = light, reduced_motion = reducedMotion, always_on_top = Topmost, interface_accent = interfaceAccent }); }
        private async Task ShowDevices() {
            await Safe(async () => { var value = await api.Get("/v1/account/devices", CancellationToken.None); RenderDeviceCards(value); });
        }
        private void RenderDeviceCards(Dictionary<string, object> value) {
            panelContent.Children.Clear();
            foreach (var device in Json.Rows(value, "devices")) {
                int deviceCard = panelContent.Children.Count; var id = Json.Text(device, "id"); var name = Json.Text(device, "name");
                panelContent.Children.Add(Label(Json.Text(device, "platform") + " · " + (Json.Flag(device, "current") ? "Это устройство" : Json.Text(device, "status") == "active" ? "Подключено" : "Доступ отозван"), 12, muted));
                if (Json.Flag(device, "current")) api.Account.DeviceId = id; else if (Json.Text(device, "status") == "active") AddPanelButton("Отозвать доступ", () => ConfirmDeviceRevocation(id, name), false);
                SurfaceGroup(deviceCard, name, "", "profile");
            }
            AddPanelButton("Назад", () => OpenPanel("Аккаунт"), false);
        }
        private async Task Logout() {
            if (busy || recorder.Recording || speaking) { SetStatus("Сначала остановите текущую задачу.", true); return; }
            await Safe(async () => {
                var devices = await api.Get("/v1/account/devices", CancellationToken.None);
                var current = Json.Rows(devices, "devices").FirstOrDefault(item => Json.Flag(item, "current"));
                if (current == null) throw new InvalidDataException("Сервер не определил текущее устройство. Выход не подтверждён.");
                await api.Call("DELETE", "/v1/account/devices/" + Uri.EscapeDataString(Json.Text(current, "id")), null, CancellationToken.None);
                CancelVoiceEnrollment(); InvalidateVoiceIdentity(); ResetDevelopmentState(); store.ForgetSession(); api.Account = new AccountSession(); api.SessionId = ""; transcript.Children.Clear(); sessions.Clear(); ShowHero(); RenderHistory(); profile.Content = "Войти"; await RenderAccount(); SetStatus("Вы вышли на этом ПК", false);
            });
        }
        private void RenderTasks(Dictionary<string, object> value, Dictionary<string, object> projects) {
            var items = Json.Rows(value, "tasks").ToList();
            int project = panelContent.Children.Count;
            RenderProjects(projects);
            SurfaceGroup(project, "Текущий проект", "", "files"); int form = panelContent.Children.Count;
            panelContent.Children.Add(Label("Название задачи", 12, muted));
            var input = Field("Название задачи", false); panelContent.Children.Add(input);
            panelContent.Children.Add(Label("Напомнить (необязательно)", 12, muted)); var date = new DatePicker { Foreground = text, Background = surface, BorderBrush = line, SelectedDate = null, Margin = new Thickness(0, 6, 0, 6) }; AccessibleName(date, "Дата напоминания"); panelContent.Children.Add(date);
            var time = Field("Время напоминания, ЧЧ:ММ", false); time.Text = "18:00"; panelContent.Children.Add(time);
            int actions = panelContent.Children.Count; AddPanelButton("Добавить дело", () => { var task = Safe(async () => { if (input.Text.Trim().Length == 0) return;
                DateTime? due = null; if (date.SelectedDate != null) { TimeSpan clock; if (!TimeSpan.TryParse(time.Text, out clock) || clock.TotalHours < 0 || clock.TotalHours >= 24) throw new InvalidOperationException("Введите время в формате ЧЧ:ММ."); var local = date.SelectedDate.Value.Date.Add(clock); if (local <= DateTime.Now) throw new InvalidOperationException("Выберите будущую дату и время."); due = local.ToUniversalTime(); }
                await EnsureProject(); await api.Call("POST", "/v1/assistant/tasks", new { title = input.Text.Trim(), action_mode = "remind", due_at = due.HasValue ? due.Value.ToString("o") : null }, CancellationToken.None); await OpenPanelTask("Дела"); }); }, true);
            AddPanelButton("Заметки проекта", () => { var task = ShowNotes(); }, false); CompactActions(actions); var formCard = SurfaceGroup(form, "Новое дело", "Добавьте задачу и, если нужно, время напоминания.", "tasks"); CollapsibleGroup(formCard, "Добавить дело", items.Count == 0);
            if (items.Count == 0) EmptyState("Пока нет дел", "Добавьте дело или скажите Тройке, о чём напомнить.", "tasks");
            foreach (var item in items) { int taskCard = panelContent.Children.Count; var id = Json.Text(item, "id"); DateTime due; if (DateTime.TryParse(Json.Text(item, "due_at"), out due)) panelContent.Children.Add(Label(due.ToLocalTime().ToString("d MMM, HH:mm"), 12, muted)); AddPanelButton("Готово", () => { var task = Safe(async () => { await api.Call("PATCH", "/v1/assistant/tasks/" + Uri.EscapeDataString(id), new { status = "completed" }, CancellationToken.None); await OpenPanelTask("Дела"); }); }, false); SurfaceGroup(taskCard, Json.Text(item, "title"), "", "tasks"); }
        }
        private void RenderMemories(Dictionary<string, object> value) {
            int preferencesCard = panelContent.Children.Count; var items = Json.Rows(value, "memories").ToList();
            object rawPreferences; var preferences = value.TryGetValue("preferences", out rawPreferences) ? rawPreferences as Dictionary<string, object> : null;
            if (preferences != null) {
                bool automaticEnabled = Json.Flag(preferences, "automatic_enabled");
                var automatic = new CheckBox { Content = "Автоматическая память", IsChecked = automaticEnabled, Foreground = text, Margin = new Thickness(0, 6, 0, 6) };
                AccessibleName(automatic, "Автоматическая память для телефона и ПК");
                panelContent.Children.Add(automatic);
                panelContent.Children.Add(Label("Помнить прямо сказанные имя, город, работу, учёбу, проекты и устойчивые предпочтения. Не каждую реплику. Настройка общая для телефона и ПК. Секреты и чувствительные темы автоматически не сохраняются; старые разговоры не обрабатываются.", 12, muted));
                RoutedEventHandler change = async (sender, args) => {
                    bool desired = automatic.IsChecked == true; automatic.IsEnabled = false;
                    await Safe(async () => {
                        var result = await api.Call("PUT", "/v1/memory-preferences", new { automatic_enabled = desired }, CancellationToken.None);
                        if (Json.Flag(result, "automatic_enabled") != desired) throw new InvalidDataException("Сервер не подтвердил настройку памяти.");
                        automaticEnabled = desired;
                        SetStatus(desired ? "Автоматическая память включена на всех устройствах" : "Автоматическая память отключена. Записи сохранены.", false);
                    });
                    automatic.IsChecked = automaticEnabled; automatic.IsEnabled = true;
                };
                automatic.Click += change;
            } else panelContent.Children.Add(Label("Для автоматической памяти требуется обновление сервера.", 12, muted));
            AddPanelButton("Добавить запись", () => EditMemory(null), true); SurfaceGroup(preferencesCard, "Что Тройка помнит о вас", "Контекст, который остаётся между разговорами.", "memory");
            if (items.Count == 0) EmptyState("Память пока пуста", "Скажите: «Запомни…» или добавьте запись вручную.", "memory");
            foreach (var item in items) { int memoryCard = panelContent.Children.Count; var memory = item; var id = Json.Text(item, "id"); var content = Json.Text(item, "content"); if (content.Length == 0) content = Json.Text(item, "text"); panelContent.Children.Add(Label(content, 14, text)); if (Json.Text(item, "source") == "automatic") { var source = Label("Сохранено автоматически", 11, muted); source.Margin = new Thickness(0, 8, 0, 0); panelContent.Children.Add(source); } int actions = panelContent.Children.Count; AddPanelButton("Изменить запись", () => EditMemory(memory), false); AddPanelButton("Удалить эту запись", () => {
                    panelContent.Children.Clear(); panelContent.Children.Add(Label("Удалить эту запись из памяти аккаунта на всех устройствах?", 15, text)); Gap();
                    AddPanelButton("Удалить", () => { var task = Safe(async () => { await api.Call("DELETE", "/v1/memories/" + Uri.EscapeDataString(id), null, CancellationToken.None); await OpenPanelTask("Память"); }); }, true); AddPanelButton("Отмена", () => OpenPanel("Память"), false);
                }, false); CompactActions(actions); SurfaceGroup(memoryCard, Json.Text(item, "title"), "", "memory"); }
        }
        private async Task RenderFiles() {
            var owner = api.Account.Email; int revision = panelRevision;
            if (api.Account.SignedIn) await Safe(ReceiveFiles); if (revision != panelRevision) return;
            panelContent.Children.Clear();
            if (owner.Length == 0) { panelContent.Children.Add(Label("Войдите, чтобы открыть файлы своего аккаунта.", 13, muted)); AddPanelButton("Войти", () => OpenPanel("Аккаунт"), true); SurfaceGroup(0, "Сохранено на этом ПК", "Документы и результаты ваших задач", "files"); return; }
            RenderFileCards(store.Files(owner).ToList());
        }
        private void RenderFileCards(List<string> files) {
            panelContent.Children.Add(Label("Сохранено на этом ПК · " + files.Count, 14, muted)); Gap();
            if (files.Count == 0) EmptyState("Здесь будут готовые файлы", "Попросите Тройку создать документ. Он сохранится здесь и будет доступен без интернета.", "files");
            foreach (var path in files.Take(80)) {
                int fileCard = panelContent.Children.Count; var filePath = path; panelContent.Children.Add(Label(File.GetLastWriteTime(path).ToString("d MMM, HH:mm") + " · " + Math.Max(1, new FileInfo(path).Length / 1024) + " КБ", 11, muted));
                int actions = panelContent.Children.Count; AddPanelButton("Открыть", () => OpenFile(filePath), true); AddPanelButton("Сохранить копию…", () => ExportFile(filePath), false); CompactActions(actions); SurfaceGroup(fileCard, Path.GetFileName(path), "", "files");
            }
            AddPanelButton("Ранее сохранённые файлы на сервере", () => { var task = ShowLegacyFiles(); }, false);
        }
        private void ExportFile(string path) {
            var save = new Microsoft.Win32.SaveFileDialog { FileName = Path.GetFileName(path), DefaultExt = Path.GetExtension(path), AddExtension = true, OverwritePrompt = true };
            if (save.ShowDialog(this) == true) { try { File.Copy(path, save.FileName, true); SetStatus("Копия сохранена", false); } catch (Exception error) { SetStatus(error.Message, true); } }
        }
        private void OpenFile(string path) {
            var supported = new[] { ".docx", ".pptx", ".xlsx", ".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".zip" };
            if (!supported.Contains(Path.GetExtension(path).ToLowerInvariant())) { SetStatus("Этот формат нельзя открыть из Тройки. Сохраните копию и выберите приложение вручную.", true); return; }
            try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); } catch { SetStatus("Для этого файла не установлено приложение.", true); }
        }
        private void OpenWeb(string url) { Uri uri; if (!Uri.TryCreate(url, UriKind.Absolute, out uri) || (uri.Scheme != "https" && uri.Scheme != "http")) return; try { Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true }); } catch { SetStatus("Не удалось открыть браузер.", true); } }
        private void ToggleCompact() {
            if (busy || recorder.Recording || speaking) { SetStatus("Сначала остановите текущую задачу.", true); return; }
            if (!compact) { expandedWidth = Width; expandedHeight = Height; compact = true; MinWidth = 440; MinHeight = 520; Width = 480; Height = 600; }
            else { compact = false; MinWidth = 780; MinHeight = 540; Width = expandedWidth; Height = expandedHeight; }
            // The same window and conversation remain alive; no auxiliary assistant window.
            ApplyCompact();
        }
        private void ApplyCompact() {
            ClosePanel(); sidebar.Visibility = compact ? Visibility.Collapsed : Visibility.Visible; body.ColumnDefinitions[0].Width = new GridLength(compact ? 0 : NavigationWidth);
            if (compact) { center.Margin = new Thickness(9, 0, 9, 0); MinWidth = 440; } else center.Margin = new Thickness(13, 0, 3, 0);
        }
        public void RenderTo(string path) {
            UpdateLayout(); var image = new RenderTargetBitmap((int)ActualWidth, (int)ActualHeight, 96, 96, PixelFormats.Pbgra32); image.Render(this);
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(image)); using (var stream = File.Create(path)) encoder.Save(stream);
        }
        public async Task PreviewLayout(string path, double width, double height, bool lightTheme, bool compactMode, string panel) {
            light = lightTheme; compact = compactMode; MinWidth = compact ? 440 : 780; MinHeight = compact ? 520 : 540; Width = width; Height = height; Build();
            if (panel.Length > 0) await OpenPanelTask(panel); UpdateLayout();
            foreach (var control in new FrameworkElement[] { microphone, send, composer }) {
                if (!control.IsVisible) continue;
                var point = control.TranslatePoint(new Point(0, 0), this);
                if (point.X < 0 || point.Y < 0 || point.X + control.ActualWidth > ActualWidth + 1 || point.Y + control.ActualHeight > ActualHeight + 1) throw new InvalidOperationException("Управление выходит за границы окна.");
            }
            RenderTo(path);
        }
    }
    public static class Program {
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern uint RegisterWindowMessage(string name);
        [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);
        public static readonly uint ActivationMessage = RegisterWindowMessage("TroikaDesktop.Activate.v1");
        [STAThread] public static int Main(string[] args) {
            if (args.Length != 0 && args[0] == ComputerUseNativeDriver.WorkerArgument)
                return ComputerUseNativeDriver.WorkerMain(args);
            if (args.Contains("--computer-use-agent")) {
                if (args.Length != 2 || args[0] != "--computer-use-agent") return 2;
                try {
                    using (var agent = new ComputerUseAgent(args[1], Environment.GetEnvironmentVariable("TROIKA_COMPUTER_LAB_TOKEN"))) {
                        var lab = new Application();
                        return lab.Run(new ComputerUsePrototypeWindow(new ComputerUseSession(), agent));
                    }
                } catch (ArgumentException error) {
                    MessageBox.Show(error.Message, "Тройка — тест управления с моделью");
                    return 2;
                }
            }
            if (args.Length == 1 && args[0] == "--computer-use-prototype") {
                var prototype = new Application();
                return prototype.Run(new ComputerUsePrototypeWindow());
            }
            System.Net.ServicePointManager.SecurityProtocol = System.Net.SecurityProtocolType.Tls12;
            bool design = args.Contains("--preview") || args.Contains("--render");
            bool acquired = false;
            using (var instance = new Mutex(false, "Local\\TroikaDesktop.Primary." + System.Security.Principal.WindowsIdentity.GetCurrent().User.Value)) {
            if (!design) {
                try { acquired = instance.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) { PostMessage(new IntPtr(0xffff), ActivationMessage, IntPtr.Zero, IntPtr.Zero); return 0; }
            }
            try {
            var app = new Application(); bool render = args.Contains("--render"); var window = new MainWindow(args.Contains("--preview") || render);
            if (render) {
                var index = Array.IndexOf(args, "--render"); var path = Path.GetFullPath(args[index + 1]);
                window.ShowActivated = false; window.ShowInTaskbar = false;
                window.Loaded += delegate { var pending = window.Dispatcher.BeginInvoke(new Action(async delegate { try { double width = args.Contains("--small") ? 780 : args.Contains("--compact") ? 480 : 960; double height = args.Contains("--small") ? 540 : args.Contains("--compact") ? 600 : 680; await window.PreviewLayout(path, width, height, args.Contains("--light"), args.Contains("--compact"), args.Contains("--development") ? "Разработка" : args.Contains("--capabilities") ? "Возможности" : ""); window.Close(); } catch (Exception error) { File.WriteAllText(path + ".error.txt", error.Message); app.Shutdown(1); } })); };
            }
            app.DispatcherUnhandledException += delegate(object sender, DispatcherUnhandledExceptionEventArgs error) { error.Handled = true; window.Title = "Тройка — ошибка, перезапустите приложение"; };
            return app.Run(window);
            } finally { if (acquired) instance.ReleaseMutex(); }
            }
        }
    }
}
