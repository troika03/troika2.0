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
        private readonly string targetId;
        private readonly DispatcherTimer timer;
        private readonly TextBlock status;
        private readonly TextBlock remaining;
        private readonly TextBox editor;
        private readonly ComputerUseAgent agent;
        private readonly ComputerUseWindowsRun windowsRun;
        private readonly bool externalEditor;
        private readonly Func<ComputerUseSession, string, IComputerUseEditor> openNotepad;
        private bool closing, allowClose;
        private CancellationTokenSource running;
        private TaskCompletionSource<bool> approval;
        private readonly StackPanel approvalPanel;
        private readonly TextBlock approvalText;
        internal readonly TextBox TaskInput;
        internal readonly ComputerUseSession Session;
        internal readonly Button AllowButton;
        internal readonly Button StopButton;
        internal readonly ComboBox PermissionMode;
        internal readonly Button ApproveActionButton;
        internal readonly Button DenyActionButton;
        internal event Action Stopped;
        internal readonly string OutputFile;
        internal Task<ComputerUseState> Execution { get; private set; }

        internal ComputerUsePrototypeWindow() : this(new ComputerUseSession()) { }

        internal ComputerUsePrototypeWindow(ComputerUseSession session, ComputerUseAgent agent = null,
                ComputerUseWindowsRun windowsRun = null, bool externalEditor = false,
                Func<ComputerUseSession, string, IComputerUseEditor> openNotepad = null) {
            Session = session;
            this.agent = agent;
            this.windowsRun = windowsRun;
            this.externalEditor = externalEditor;
            this.openNotepad = openNotepad;
            targetId = (externalEditor ? ComputerUseNativeDriver.ExternalWindowPrefix : ComputerUseNativeDriver.ScratchpadWindowPrefix)
                + Guid.NewGuid().ToString("N");
            string documentId = Guid.NewGuid().ToString("N");
            OutputFile = Path.Combine(Path.GetTempPath(), "TroikaComputerUse-" + documentId,
                openNotepad == null ? "preview.txt" : "troika-notepad-" + documentId + ".txt");
            Title = openNotepad != null ? "Тройка — проба Блокнота" : externalEditor ? "Тестовый редактор Тройки"
                : windowsRun != null ? "Тройка — управление тестовым редактором"
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
            var heading = Text(openNotepad != null ? "Проба Блокнота" : windowsRun != null ? "Тестовый редактор Windows"
                : agent == null ? "Проба управления Windows" : "Тест управления с моделью");
            heading.FontSize = 22;
            heading.FontWeight = FontWeights.SemiBold;
            body.Children.Add(heading);
            if (openNotepad != null) {
                body.Children.Add(Text(windowsRun == null
                    ? "Тройка откроет отдельный классический Блокнот с пустым пробным файлом. Выберите, можно ли ввести и сохранить образец."
                    : "Запуск " + windowsRun.RunLabel + ". Тройка откроет отдельный Блокнот с пустым файлом. Выберите доступ для этого окна."));
                Closing += CloseActiveRun;
            } else if (windowsRun != null) {
                body.Children.Add(Text("Запрос " + windowsRun.RunLabel + ". Тройка сможет осмотреть этот редактор, ввести текст задачи и сохранить временный файл."));
                Closing += CloseActiveRun;
            } else if (agent == null) {
                body.Children.Add(Text("Разрешить Тройке заполнить тестовый редактор и сохранить образец в отдельный временный файл."));
            } else {
                body.Children.Add(Text("Текст задачи отправится в OpenRouter. Доступ ограничен этим редактором и отдельным временным файлом."));
                body.Children.Add(Text("Задача для тестового редактора"));
                TaskInput = new TextBox { MaxLength = 512, MinHeight = 36, Margin = new Thickness(0, 0, 0, 12), Padding = new Thickness(8) };
                AutomationProperties.SetName(TaskInput, "Задача для тестового редактора");
                body.Children.Add(TaskInput);
            }
            bool assisted = openNotepad != null || (windowsRun != null && windowsRun.Assisted);
            if (assisted) {
                body.Children.Add(Text(openNotepad == null ? "Доступ к этому редактору" : "Доступ к пробному файлу"));
                PermissionMode = new ComboBox { MinHeight = 32, Margin = new Thickness(0, 0, 0, 12) };
                PermissionMode.Items.Add("Всегда спрашивать перед изменением");
                PermissionMode.Items.Add("Разрешить действия в этом окне до конца запуска");
                PermissionMode.Items.Add("Только просмотр");
                PermissionMode.SelectedIndex = 0;
                AutomationProperties.SetName(PermissionMode, "Режим разрешений");
                body.Children.Add(PermissionMode);
            }
            var actions = new WrapPanel();
            AllowButton = ButtonFor(assisted ? "Подтвердить режим" : "Разрешить и запустить", Start);
            StopButton = ButtonFor("Остановить (Esc)", Stop);
            actions.Children.Add(AllowButton);
            actions.Children.Add(StopButton);
            body.Children.Add(actions);
            remaining = Text("");
            body.Children.Add(remaining);
            status = Text("Ожидаю разрешения.");
            body.Children.Add(status);
            if (assisted) {
                approvalPanel = new StackPanel { Visibility = Visibility.Collapsed };
                approvalText = Text("");
                approvalPanel.Children.Add(approvalText);
                var approvalButtons = new WrapPanel();
                ApproveActionButton = ButtonFor("Разрешить действие", () => ResolveApproval(true));
                DenyActionButton = ButtonFor("Отклонить", () => ResolveApproval(false));
                approvalButtons.Children.Add(ApproveActionButton);
                approvalButtons.Children.Add(DenyActionButton);
                approvalPanel.Children.Add(approvalButtons);
                body.Children.Add(approvalPanel);
            }

            if (openNotepad == null) {
                body.Children.Add(Text("Тестовый редактор"));
                editor = externalEditor ? new ComputerUseEditorField(Session) : new TextBox();
                editor.IsReadOnly = true;
                editor.MinHeight = 64;
                editor.TextWrapping = TextWrapping.Wrap;
                editor.Padding = new Thickness(8);
                AutomationProperties.SetName(editor, "Тестовый текст");
                AutomationProperties.SetAutomationId(editor, targetId + "-editor");
                body.Children.Add(editor);
                var fixture = new WrapPanel();
                if (!externalEditor) {
                    fixture.Children.Add(FixtureButton("Запись образца", "write", ComputerUseStep.Write, value => {
                        if (editor.Text.Length != 0) return false;
                        editor.Text = value;
                        return true;
                    }));
                }
                fixture.Children.Add(FixtureButton("Сохранение файла", "save", ComputerUseStep.Save, Save));
                body.Children.Add(fixture);
            }
            Content = body;

            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
            timer.Tick += (sender, args) => Refresh();
            PreviewKeyDown += (sender, args) => {
                if (args.Key == Key.Escape) { args.Handled = true; Stop(); }
            };
            Closed += (sender, args) => { Stop(); timer.Stop(); };
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
                string policy = PermissionMode == null ? null : new[] { "ask", "window", "view" }[PermissionMode.SelectedIndex];
                var approve = policy == "ask" ? (Func<string, string, TimeSpan, Task<bool>>)ApproveMutation : null;
                if (openNotepad != null) Execution = RunNotepadAsync(policy, approve, running.Token);
                else {
                    var executor = new ComputerUseExecutor(Session, new WindowInteropHelper(this).Handle, targetId, OutputFile,
                        isolated: agent != null || windowsRun != null, externalEditor: externalEditor,
                        observationSeconds: PermissionMode == null ? ComputerUseExecutor.ObservationSeconds : 30);
                    if (windowsRun != null) Execution = windowsRun.RunAsync(Session, executor, running.Token, policy, approve);
                    else Execution = agent == null ? executor.RunAsync() : agent.RunAsync(Session, executor, goal, running.Token);
                }
                await Execution;
            } catch (Exception) {
                Session.Finish(false);
            } finally {
                running.Dispose();
                running = null;
                Refresh();
            }
        }

        private async Task<ComputerUseState> RunNotepadAsync(string policy,
                Func<string, string, TimeSpan, Task<bool>> approve, CancellationToken cancellation) {
            try {
                var target = await Task.Run(() => openNotepad(Session, OutputFile)).ConfigureAwait(false);
                using (target as IDisposable) {
                    var executor = new ComputerUseExecutor(Session, target, OutputFile, new UTF8Encoding(true, true), 30);
                    return windowsRun == null
                        ? await executor.RunAsync(policy, approve).ConfigureAwait(false)
                        : await windowsRun.RunAsync(Session, executor, cancellation, policy, approve).ConfigureAwait(false);
                }
            } catch (IOException) { }
            catch (Win32Exception) { }
            catch (InvalidOperationException) { }
            catch (UnauthorizedAccessException) { }
            return Session.Finish(false);
        }

        private void CancelRequest() { if (running != null) running.Cancel(); }

        internal void Stop() {
            bool notify = Session.State == ComputerUseState.Pending || Session.State == ComputerUseState.Active;
            Session.Stop();
            ResolveApproval(false);
            CancelRequest();
            Refresh();
            var stopped = Stopped;
            if (notify && stopped != null) stopped();
        }

        private Task<bool> ApproveMutation(string action, string text, TimeSpan timeLeft) {
            return Dispatcher.InvokeAsync(() => ShowApprovalAsync(action, text, timeLeft)).Task.Unwrap();
        }

        private async Task<bool> ShowApprovalAsync(string action, string text, TimeSpan timeLeft) {
            if (Session.State != ComputerUseState.Active || timeLeft <= TimeSpan.Zero) return false;
            approval = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            approvalText.Text = action == "write" ? "Разрешить ввести текст?\n" + text
                : "Разрешить сохранить и проверить временный файл?\n" + OutputFile;
            ApproveActionButton.Content = action == "write" ? "Разрешить ввод" : "Разрешить сохранение";
            approvalPanel.Visibility = Visibility.Visible;
            try {
                var decision = approval.Task;
                return await Task.WhenAny(decision, Task.Delay(timeLeft)) == decision && await decision;
            } finally {
                approval = null;
                approvalText.Text = "";
                approvalPanel.Visibility = Visibility.Collapsed;
            }
        }

        private void ResolveApproval(bool allowed) {
            if (approval != null) approval.TrySetResult(allowed);
        }

        private async void CloseActiveRun(object sender, CancelEventArgs args) {
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
            if (PermissionMode != null) PermissionMode.IsEnabled = state == ComputerUseState.Pending;
            StopButton.IsEnabled = state == ComputerUseState.Pending || state == ComputerUseState.Active;
            remaining.Text = state == ComputerUseState.Active ? "Доступ ещё " + Session.SecondsRemaining + " с" : "";
            remaining.Visibility = state == ComputerUseState.Active ? Visibility.Visible : Visibility.Collapsed;
            if (state != ComputerUseState.Active) {
                ResolveApproval(false);
                timer.Stop();
                if (state == ComputerUseState.Expired) CancelRequest();
            }
            switch (state) {
                case ComputerUseState.Active: status.Text = openNotepad == null ? "Выполняю пробу в тестовом редакторе." : "Выполняю пробу Блокнота."; break;
                case ComputerUseState.Stopped: status.Text = "Остановлено."; break;
                case ComputerUseState.Expired: status.Text = "Срок разрешения истёк."; break;
                case ComputerUseState.Verified: status.Text = "Файл сохранён и проверен.\n" + OutputFile; break;
                case ComputerUseState.Completed: status.Text = openNotepad == null ? "Модель закончила работу. Файл не создан."
                    : "Проба завершена. Пробный файл остался пустым."; break;
                case ComputerUseState.Failed: status.Text = openNotepad == null ? "Не удалось подтвердить сохранение образца."
                    : "Не удалось завершить пробу Блокнота."; break;
            }
        }
    }
}
