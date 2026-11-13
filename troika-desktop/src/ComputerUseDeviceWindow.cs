using System;
using System.ComponentModel;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace Troika.Desktop {
    internal sealed class ComputerUseDeviceWindow : Window {
        private const string Example = "Открой Блокнот, введи «Проба Тройки» и сохрани. Затем открой обзор в браузере и нажми «Доставка».";
        private readonly ComputerUseDeviceRun run;
        private readonly StackPanel form, approval, browserScope;
        private readonly WrapPanel pageActions;
        private readonly TextBlock selected, approvalText;
        private readonly Button reset;
        private readonly CheckBox mobile, share;
        private string project, entry, secondEntry;
        private CancellationTokenSource running;
        private TaskCompletionSource<bool> decision;
        private bool closing, allowClose;
        internal readonly TextBox Goal;
        internal readonly ComboBox Permission;
        internal readonly CheckBox Browser, Notepad, SystemPointer;
        internal readonly Button StartButton, StopButton, ApproveButton, DenyButton;
        internal readonly TextBlock Status;
        internal string PendingAction { get { return approvalText.Text; } }
        internal Task Execution { get; private set; }

        internal ComputerUseDeviceWindow(ComputerUseDeviceRun run) {
            this.run = run;
            Title = "Тройка — управление ПК";
            Width = 550;
            Height = 620;
            MinWidth = 390;
            MinHeight = 400;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            FontFamily = BrandAssets.Font;
            FontSize = 14;
            Background = Brush(250, 252, 249);
            Foreground = Brush(32, 35, 34);
            if (SystemParameters.HighContrast) {
                SetResourceReference(BackgroundProperty, SystemColors.WindowBrushKey);
                SetResourceReference(ForegroundProperty, SystemColors.WindowTextBrushKey);
            }

            var layout = new DockPanel();
            var footer = new StackPanel { Margin = new Thickness(24, 8, 24, 16) };
            DockPanel.SetDock(footer, Dock.Bottom);
            layout.Children.Add(footer);
            form = new StackPanel { Margin = new Thickness(24, 22, 24, 0) };
            layout.Children.Add(new ScrollViewer { Content = form, VerticalScrollBarVisibility = ScrollBarVisibility.Auto });

            var title = Text("Управление ПК");
            title.FontSize = 26;
            title.FontWeight = FontWeights.Medium;
            form.Children.Add(title);
            form.Children.Add(Text("Задача"));
            Goal = new TextBox { Text = Example, MaxLength = 512, TextWrapping = TextWrapping.Wrap, MinHeight = 62,
                Padding = new Thickness(8), Margin = new Thickness(0, 0, 0, 16) };
            AutomationProperties.SetName(Goal, "Задача для ПК");
            form.Children.Add(Goal);

            form.Children.Add(Text("Разрешённые приложения"));
            var apps = new WrapPanel { Margin = new Thickness(0, 0, 0, 12) };
            Browser = new CheckBox { Content = "Браузер", IsChecked = true, Margin = new Thickness(0, 0, 18, 0) };
            Notepad = new CheckBox { Content = "Блокнот", IsChecked = true };
            apps.Children.Add(Browser);
            apps.Children.Add(Notepad);
            form.Children.Add(apps);

            browserScope = new StackPanel();
            form.Children.Add(browserScope);
            browserScope.Children.Add(Text("Страницы браузера"));
            selected = Text("");
            browserScope.Children.Add(selected);
            var sourceActions = new WrapPanel();
            sourceActions.Children.Add(ButtonFor("Выбрать папку сайта", ChooseFolder));
            reset = ButtonFor("Пробные страницы", () => SetProject(null, null, null));
            sourceActions.Children.Add(reset);
            browserScope.Children.Add(sourceActions);
            pageActions = new WrapPanel();
            pageActions.Children.Add(ButtonFor("Главная страница", () => ChoosePage(false)));
            pageActions.Children.Add(ButtonFor("Вторая страница", () => ChoosePage(true)));
            pageActions.Children.Add(ButtonFor("Оставить одну", () => SetProject(project, entry, null)));
            browserScope.Children.Add(pageActions);

            mobile = new CheckBox { Content = "Мобильный размер страницы", Margin = new Thickness(0, 0, 0, 10) };
            const string shareLabel = "Передать видимые заголовки и подписи ссылок в OpenRouter";
            share = new CheckBox { Content = new TextBlock { Text = shareLabel, TextWrapping = TextWrapping.Wrap },
                Margin = new Thickness(0, 0, 0, 10) };
            AutomationProperties.SetName(share, shareLabel);
            browserScope.Children.Add(mobile);
            browserScope.Children.Add(share);

            form.Children.Add(Text("Режим разрешений"));
            Permission = new ComboBox { MinHeight = 34, Margin = new Thickness(0, 0, 0, 12) };
            Permission.Items.Add("Всегда спрашивать перед действием");
            Permission.Items.Add("Разрешить действия в выбранных приложениях");
            Permission.Items.Add("Только просмотр");
            Permission.SelectedIndex = 0;
            AutomationProperties.SetName(Permission, "Режим разрешений");
            form.Children.Add(Permission);
            const string pointerLabel = "Двигать системный курсор в Блокноте";
            SystemPointer = new CheckBox { Content = Text(pointerLabel), Margin = new Thickness(0, 0, 0, 8) };
            AutomationProperties.SetName(SystemPointer, pointerLabel);
            form.Children.Add(SystemPointer);

            approval = new StackPanel { Visibility = Visibility.Collapsed };
            approvalText = Text("");
            approval.Children.Add(new ScrollViewer { Content = approvalText, MaxHeight = 148,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto });
            var choices = new WrapPanel();
            ApproveButton = ButtonFor("Разрешить действие", () => Resolve(true));
            DenyButton = ButtonFor("Отклонить", () => Resolve(false));
            choices.Children.Add(ApproveButton);
            choices.Children.Add(DenyButton);
            approval.Children.Add(choices);
            footer.Children.Add(approval);

            var actions = new WrapPanel();
            StartButton = ButtonFor("Запустить", () => Execution = Execute());
            StartButton.IsDefault = true;
            if (!SystemParameters.HighContrast) {
                StartButton.Background = Brush(40, 103, 71);
                StartButton.Foreground = Brushes.White;
            }
            StopButton = ButtonFor("Остановить (Esc)", Stop);
            actions.Children.Add(StartButton);
            actions.Children.Add(StopButton);
            footer.Children.Add(actions);
            Status = Text("");
            Status.Margin = new Thickness(0);
            AutomationProperties.SetLiveSetting(Status, AutomationLiveSetting.Polite);
            footer.Children.Add(Status);
            Content = layout;

            Goal.TextChanged += (sender, args) => Refresh();
            Browser.Checked += (sender, args) => Refresh();
            Browser.Unchecked += (sender, args) => Refresh();
            Notepad.Checked += (sender, args) => Refresh();
            Notepad.Unchecked += (sender, args) => Refresh();
            Permission.SelectionChanged += (sender, args) => Refresh();
            PreviewKeyDown += (sender, args) => {
                if (args.Key == Key.Escape && running != null) { args.Handled = true; Stop(); }
            };
            Closing += CloseAfterStop;
            SetProject(null, null, null);
        }

        private static Brush Brush(byte red, byte green, byte blue) {
            return new SolidColorBrush(Color.FromRgb(red, green, blue));
        }

        private static TextBlock Text(string value) {
            return new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, LineHeight = 22,
                Margin = new Thickness(0, 0, 0, 8) };
        }

        private static Button ButtonFor(string value, Action invoke) {
            var button = new Button { Content = value, MinHeight = 36, Margin = new Thickness(0, 0, 8, 8),
                Padding = new Thickness(12, 4, 12, 4) };
            button.Click += (sender, args) => invoke();
            return button;
        }

        internal void SetProject(string folder, string first, string second) {
            bool changed = project != folder;
            project = folder;
            entry = first;
            secondEntry = second;
            selected.Text = folder == null ? "Пробные страницы Тройки"
                : folder + "\n" + (first ?? "Выберите главную страницу") + (second == null ? "" : " · " + second);
            Visibility visible = folder == null ? Visibility.Collapsed : Visibility.Visible;
            pageActions.Visibility = reset.Visibility = share.Visibility = visible;
            if (changed) share.IsChecked = false;
            if (folder != null && Goal.Text == Example)
                Goal.Text = "Осмотри главную страницу. Прокрути и проверь, какие разделы видны.";
            Refresh();
        }

        private void ChooseFolder() {
            using (var dialog = new System.Windows.Forms.FolderBrowserDialog { Description = "Выберите папку сайта", ShowNewFolderButton = false }) {
                if (dialog.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;
                string path = dialog.SelectedPath;
                SetProject(path, File.Exists(Path.Combine(path, "index.html")) ? "index.html" : null, null);
            }
        }

        private void ChoosePage(bool second) {
            var dialog = new Microsoft.Win32.OpenFileDialog { InitialDirectory = project, Filter = "HTML-страницы|*.html;*.htm",
                CheckFileExists = true };
            if (dialog.ShowDialog(this) != true) return;
            string root = Path.GetFullPath(project).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string path = Path.GetFullPath(dialog.FileName);
            if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase)) {
                Status.Text = "Выберите HTML-страницу из выбранной папки.";
                return;
            }
            string relative = path.Substring(root.Length).Replace(Path.DirectorySeparatorChar, '/');
            SetProject(project, second ? entry : relative, second ? relative : secondEntry);
        }

        private void Refresh() {
            bool active = running != null;
            bool browser = Browser.IsChecked == true;
            browserScope.Visibility = browser ? Visibility.Visible : Visibility.Collapsed;
            SystemPointer.Visibility = Notepad.IsChecked == true && Permission.SelectedIndex != 2 ? Visibility.Visible : Visibility.Collapsed;
            form.IsEnabled = !active && !closing;
            StartButton.IsEnabled = !active && !closing && ComputerUseAgent.ValidGoal(Goal.Text.Trim())
                && (browser || Notepad.IsChecked == true)
                && (!browser || project == null || (entry != null && !String.Equals(entry, secondEntry, StringComparison.OrdinalIgnoreCase)));
            StopButton.IsEnabled = active && !running.IsCancellationRequested;
        }

        private async Task Execute() {
            if (!StartButton.IsEnabled) return;
            string goal = Goal.Text.Trim();
            bool browser = Browser.IsChecked == true;
            string[] apps = browser ? (Notepad.IsChecked == true ? new[] { "browser", "notepad" } : new[] { "browser" })
                : new[] { "notepad" };
            var options = new ComputerUseDeviceOptions { Apps = apps, Project = browser ? project : null,
                Entry = browser ? entry : null, SecondEntry = browser ? secondEntry : null,
                Mobile = browser && mobile.IsChecked == true, ShareHeadings = browser && share.IsChecked == true,
                SystemPointer = SystemPointer.Visibility == Visibility.Visible && SystemPointer.IsChecked == true,
                Permission = new[] { "ask", "run", "view" }[Permission.SelectedIndex] };
            running = new CancellationTokenSource(TimeSpan.FromSeconds(150));
            Status.Text = "Запускаю задачу на этом ПК…";
            Refresh();
            try {
                Status.Text = await run.ExecuteAsync(goal, options, Ask, text => {
                    if (!running.IsCancellationRequested) Status.Text = text;
                }, running.Token);
            } catch (ApiException) { Status.Text = "Тестовый сервер не запустил задачу или отклонил разрешение."; }
            catch (HttpRequestException) { Status.Text = "Тестовый сервер недоступен."; }
            catch (OperationCanceledException) { Status.Text = "Задача остановлена."; }
            catch (ComputerUsePointerInterruptedException) { Status.Text = "Клик прерван. Проверьте, что поле Блокнота видно и мышь свободна."; }
            catch (IOException) { Status.Text = "Не удалось получить подтверждённый результат."; }
            catch (Win32Exception) { Status.Text = "Не удалось запустить управление ПК."; }
            catch (InvalidOperationException) { Status.Text = "Завершение задачи не подтверждено."; }
            catch (ArgumentException) { Status.Text = "Проверьте выбранные страницы и задачу."; }
            finally { running.Dispose(); running = null; Refresh(); }
        }

        private async Task<bool> Ask(string app, string action, string target, TimeSpan timeLeft) {
            if (running.IsCancellationRequested) return false;
            string page = target == "overview" ? entry ?? "обзор" : secondEntry ?? "сведения";
            if (app == "notepad") {
                approvalText.Text = action == "write" ? "Ввести в Блокнот этот текст?\n" + target
                    : action == "save" ? "Сохранить пробный файл Блокнота?" : "Открыть отдельный Блокнот?";
                if (action == "write" && SystemPointer.IsChecked == true)
                    approvalText.Text = "Нажать поле системным курсором и ввести текст?\n" + target;
            } else if (action == "click") {
                approvalText.Text = "Нажать ссылку «" + target + "»?";
            } else {
                approvalText.Text = action == "scroll" ? "Прокрутить страницу " + (target == "up" ? "вверх?" : "вниз?")
                    : (action == "open" ? "Открыть «" : "Переключиться на «") + page + "»?";
            }
            decision = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            approval.Visibility = Visibility.Visible;
            using (running.Token.Register(() => Resolve(false))) {
                try {
                    var answer = decision.Task;
                    return await Task.WhenAny(answer, Task.Delay(timeLeft)) == answer && await answer;
                } finally { decision = null; approval.Visibility = Visibility.Collapsed; }
            }
        }

        private void Resolve(bool allowed) {
            var pending = decision;
            if (pending != null) pending.TrySetResult(allowed);
        }

        private void Stop() {
            if (running == null || running.IsCancellationRequested) return;
            Status.Text = "Останавливаю задачу…";
            running.Cancel();
            Resolve(false);
            Refresh();
        }

        private async void CloseAfterStop(object sender, CancelEventArgs args) {
            if (allowClose || running == null) return;
            args.Cancel = true;
            if (closing) return;
            closing = true;
            Stop();
            await Execution;
            allowClose = true;
            Close();
        }
    }
}
