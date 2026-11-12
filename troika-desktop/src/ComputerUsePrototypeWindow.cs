using System;
using System.ComponentModel;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;

namespace Troika.Desktop {
    internal sealed class ComputerUsePrototypeWindow : Window {
        private readonly string targetId = "troika-scratchpad-" + Guid.NewGuid().ToString("N");
        private readonly DispatcherTimer timer;
        private readonly TextBlock status;
        private readonly TextBlock remaining;
        private readonly TextBox editor;
        private readonly ComputerUseAgent agent;
        private readonly ComputerUseWindowsRun windowsRun;
        private bool closing, allowClose;
        private CancellationTokenSource running;
        internal readonly TextBox TaskInput;
        internal readonly ComputerUseSession Session;
        internal readonly Button AllowButton;
        internal readonly Button StopButton;
        internal readonly string OutputFile;
        internal Task<ComputerUseState> Execution { get; private set; }

        internal ComputerUsePrototypeWindow() : this(new ComputerUseSession()) { }

        internal ComputerUsePrototypeWindow(ComputerUseSession session, ComputerUseAgent agent = null,
                ComputerUseWindowsRun windowsRun = null) {
            Session = session;
            this.agent = agent;
            this.windowsRun = windowsRun;
            OutputFile = Path.Combine(Path.GetTempPath(), "TroikaComputerUse-" + Guid.NewGuid().ToString("N"), "preview.txt");
            Title = windowsRun != null ? "Тройка — управление тестовым редактором"
                : agent == null ? "Тройка — проба управления Windows" : "Тройка — тест управления с моделью";
            Width = 540;
            MinWidth = 380;
            SizeToContent = SizeToContent.Height;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            FontFamily = new FontFamily("Segoe UI");
            FontSize = 14;
            SetResourceReference(BackgroundProperty, SystemColors.WindowBrushKey);
            SetResourceReference(ForegroundProperty, SystemColors.WindowTextBrushKey);
            AutomationProperties.SetAutomationId(this, targetId);

            var body = new StackPanel { Margin = new Thickness(24) };
            var heading = Text(windowsRun != null ? "Тестовый редактор Windows"
                : agent == null ? "Проба управления Windows" : "Тест управления с моделью");
            heading.FontSize = 22;
            heading.FontWeight = FontWeights.SemiBold;
            body.Children.Add(heading);
            if (windowsRun != null) {
                body.Children.Add(Text("Запрос " + windowsRun.RunLabel + ". Тройка сможет осмотреть этот редактор, ввести пробную строку и сохранить временный файл."));
                Closing += CloseWindowsRun;
            } else if (agent == null) {
                body.Children.Add(Text("Разрешить Тройке заполнить тестовый редактор и сохранить образец в отдельный временный файл."));
            } else {
                body.Children.Add(Text("Текст задачи отправится в OpenRouter. Доступ ограничен этим редактором и отдельным временным файлом."));
                body.Children.Add(Text("Задача для тестового редактора"));
                TaskInput = new TextBox { MaxLength = 512, MinHeight = 36, Margin = new Thickness(0, 0, 0, 12), Padding = new Thickness(8) };
                AutomationProperties.SetName(TaskInput, "Задача для тестового редактора");
                body.Children.Add(TaskInput);
            }
            var actions = new WrapPanel();
            AllowButton = ButtonFor("Разрешить и запустить", Start);
            StopButton = ButtonFor("Остановить (Esc)", Stop);
            actions.Children.Add(AllowButton);
            actions.Children.Add(StopButton);
            body.Children.Add(actions);
            remaining = Text("");
            body.Children.Add(remaining);
            status = Text("Ожидаю разрешения.");
            body.Children.Add(status);

            body.Children.Add(Text("Тестовый редактор"));
            editor = new TextBox { IsReadOnly = true, MinHeight = 64, TextWrapping = TextWrapping.Wrap, Padding = new Thickness(8) };
            AutomationProperties.SetName(editor, "Тестовый текст");
            AutomationProperties.SetAutomationId(editor, targetId + "-editor");
            body.Children.Add(editor);
            var fixture = new WrapPanel();
            fixture.Children.Add(FixtureButton("Запись образца", "write", ComputerUseStep.Write, value => {
                if (editor.Text.Length != 0) return false;
                editor.Text = value;
                return true;
            }));
            fixture.Children.Add(FixtureButton("Сохранение файла", "save", ComputerUseStep.Save, Save));
            body.Children.Add(fixture);
            Content = body;

            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
            timer.Tick += (sender, args) => Refresh();
            PreviewKeyDown += (sender, args) => {
                if (args.Key == Key.Escape) { args.Handled = true; Stop(); }
            };
            Closed += (sender, args) => { Session.Stop(); CancelRequest(); timer.Stop(); };
            if (TaskInput != null) TaskInput.TextChanged += (sender, args) => Refresh();
            Refresh();
        }

        private static TextBlock Text(string value) {
            return new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 12) };
        }

        private static Button ButtonFor(string label, Action action) {
            var button = new Button { Content = label, MinHeight = 34, Margin = new Thickness(0, 0, 8, 10), Padding = new Thickness(12, 4, 12, 4) };
            button.Click += (sender, args) => action();
            return button;
        }

        private Button FixtureButton(string label, string suffix, ComputerUseStep step, Func<string, bool> action) {
            var button = ButtonFor(label, () => {
                var permit = Session.Consume(step);
                if (permit == null) return;
                bool applied = false;
                try { applied = action(permit.Text); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
                finally { Session.Report(permit, applied); }
            });
            button.Focusable = false;
            button.IsTabStop = false;
            button.IsHitTestVisible = false;
            AutomationProperties.SetAutomationId(button, targetId + "-" + suffix);
            return button;
        }

        private bool Save(string expected) {
            if (string.IsNullOrEmpty(expected) || editor.Text != expected) return false;
            Directory.CreateDirectory(Path.GetDirectoryName(OutputFile));
            byte[] data = Encoding.UTF8.GetBytes(editor.Text);
            using (var output = new FileStream(OutputFile, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                output.Write(data, 0, data.Length);
            }
            return true;
        }

        private async void Start() {
            string goal = TaskInput == null ? null : TaskInput.Text.Trim();
            if (agent != null && !ComputerUseAgent.ValidGoal(goal)) return;
            if (!Session.Allow()) return;
            running = new CancellationTokenSource();
            Refresh();
            timer.Start();
            try {
                var executor = new ComputerUseExecutor(Session, new WindowInteropHelper(this).Handle, targetId, OutputFile,
                    isolated: agent != null || windowsRun != null);
                if (windowsRun != null) Execution = windowsRun.RunAsync(Session, executor, running.Token);
                else Execution = agent == null ? executor.RunAsync() : agent.RunAsync(Session, executor, goal, running.Token);
                await Execution;
            } catch (Exception) {
                Session.Finish(false);
            } finally {
                running.Dispose();
                running = null;
                Refresh();
            }
        }

        private void CancelRequest() { if (running != null) running.Cancel(); }

        private void Stop() { Session.Stop(); CancelRequest(); Refresh(); }

        private async void CloseWindowsRun(object sender, CancelEventArgs args) {
            if (allowClose || running == null) return;
            args.Cancel = true;
            if (closing) return;
            closing = true;
            Stop();
            try { await Execution; }
            catch (Exception) { Session.Finish(false); }
            await Dispatcher.Yield(DispatcherPriority.Background);
            allowClose = true;
            Close();
        }

        private void Refresh() {
            var state = Session.State;
            AllowButton.IsEnabled = state == ComputerUseState.Pending && (TaskInput == null || ComputerUseAgent.ValidGoal(TaskInput.Text.Trim()));
            if (TaskInput != null) TaskInput.IsReadOnly = state != ComputerUseState.Pending;
            StopButton.IsEnabled = state == ComputerUseState.Pending || state == ComputerUseState.Active;
            remaining.Text = state == ComputerUseState.Active ? "Доступ ещё " + Session.SecondsRemaining + " с" : "";
            remaining.Visibility = state == ComputerUseState.Active ? Visibility.Visible : Visibility.Collapsed;
            if (state != ComputerUseState.Active) {
                timer.Stop();
                if (state == ComputerUseState.Expired) CancelRequest();
            }
            switch (state) {
                case ComputerUseState.Active: status.Text = "Выполняю пробу в тестовом редакторе."; break;
                case ComputerUseState.Stopped: status.Text = "Остановлено."; break;
                case ComputerUseState.Expired: status.Text = "Срок разрешения истёк."; break;
                case ComputerUseState.Verified: status.Text = "Образец сохранён и проверен.\n" + OutputFile; break;
                case ComputerUseState.Completed: status.Text = "Модель закончила работу. Файл не создан."; break;
                case ComputerUseState.Failed: status.Text = "Не удалось подтвердить сохранение образца."; break;
            }
        }
    }
}
