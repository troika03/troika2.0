using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private const string ChatGptProjectHelp = "Проект для чатов создаётся в меню «Новый проект» в ChatGPT. Через эту связку Codex может работать с проектом в папке на этом ПК.";
        private readonly Queue<string> codexReports = new Queue<string>();
        private readonly DispatcherTimer codexTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        private CancellationTokenSource codexRun, codexAuth;
        private string codexExe = "", codexOwner = "", codexFolder = "", codexSession = "";
        private string codexState = "", codexConnection = "";
        private readonly Queue<string> codexFollowups = new Queue<string>();
        private bool codexConfirming;
        private TextBlock codexProgressLabel;

        private void InitializeCodex(string executable) {
            if (preview) return;
            codexExe = executable;
            codexTimer.Tick += async delegate {
                if (codexOwner.Length > 0 && (!api.Account.SignedIn || codexOwner != api.Account.Email)) ResetCodexAccount();
                await SpeakCodexReport();
            };
            codexTimer.Start();
        }
        private void ResetCodexAccount() {
            if (codexRun != null) codexRun.Cancel();
            if (codexAuth != null) codexAuth.Cancel();
            if (projectSpeech != null) projectSpeech.Cancel();
            codexOwner = ""; codexFolder = ""; codexSession = ""; codexState = ""; codexConnection = "";
            codexReports.Clear(); codexFollowups.Clear(); codexCard = null;
            if (!closed && openPanel == "Codex") RenderCodex();
        }
        private void RenderCodex() {
            panelContent.Children.Clear();
            codexProgressLabel = null;
            if (!api.Account.SignedIn) {
                panelContent.Children.Add(Label("Войдите в Тройку, чтобы открыть разработку.", 14, text));
                AddPanelButton("Войти в Тройку", () => OpenPanel("Аккаунт"), true);
                return;
            }
            panelContent.Children.Add(Label("Codex для разработки", 22, text));
            panelContent.Children.Add(Label("Тройка Pro передаёт задачи разработки из разговора в локальный Codex. Доступ и лимиты Codex определяет ваш аккаунт ChatGPT.", 13, muted));
            string owner = api.Account.Email;
            Check("Подключать Codex к задачам разработки", CodexRoutingEnabled(owner), enabled => SetCodexRouting(owner, enabled));
            if (codexConnection.Length > 0) panelContent.Children.Add(Label(codexConnection, 13, text));
            if (codexAuth == null && codexRun == null) {
                AddPanelButton("Проверить подключение", () => { var pending = ConnectCodex(false); }, false);
                AddPanelButton("Войти через ChatGPT", () => { var pending = ConnectCodex(true); }, false);
                AddPanelButton("Выбрать codex.exe…", ChooseCodexExecutable, false);
                AddPanelButton("Папка для новых проектов…", ChooseCodexProjectsLocation, false);
            } else if (codexAuth != null) AddPanelButton("Отменить вход", () => codexAuth.Cancel(), false);
            var project = CurrentCodexProject();
            if (project != null && project.Thread.Length > 0)
                AddPanelButton("Открыть чат проекта в Codex", () => OpenCodexThread(project.Thread), false);
            if (codexRun != null) {
                codexProgressLabel = Label(codexState, 14, text);
                panelContent.Children.Add(codexProgressLabel);
                AddPanelButton("Остановить задачу разработки", StopCodex, false);
            }
            panelContent.Children.Add(Label("В разговоре скажите, например, «Сделай сайт-портфолио», а затем «Добавь форму связи».", 13, muted));
        }
        private void ChooseCodexExecutable() {
            var picker = new Microsoft.Win32.OpenFileDialog { Filter = "Codex CLI (codex.exe)|codex.exe", CheckFileExists = true, Title = "Выберите установленный Codex CLI" };
            if (picker.ShowDialog(this) != true) return;
            codexExe = picker.FileName; codexConnection = "Codex выбран. Проверьте подключение.";
            SaveSettings(); RenderCodex();
        }
        private string RequireCodex() {
            string executable = LocalCodex.FindExecutable(codexExe);
            if (executable.Length == 0)
                throw new InvalidOperationException("Установите Codex CLI или выберите путь к установленному codex.exe.");
            return executable;
        }
        private string CodexProjectsLocationPreference(string owner) {
            return Path.Combine(store.FilesFolder(owner), ".codex-project-location.txt");
        }
        private string CodexProjectsRoot(string owner) {
            string location = "";
            try { location = File.ReadAllText(CodexProjectsLocationPreference(owner)); }
            catch (IOException) { }
            return LocalCodex.ProjectRoot(store, owner, location);
        }
        private void ChooseCodexProjectsLocation() {
            if (!api.Account.SignedIn) return;
            using (var picker = new System.Windows.Forms.FolderBrowserDialog { Description = "В этой папке Тройка создаст каталог Troika Codex" }) {
                if (picker.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;
                try {
                    string path = LocalCodex.ValidateWorkspace(picker.SelectedPath);
                    LocalStore.WriteAtomic(CodexProjectsLocationPreference(api.Account.Email), System.Text.Encoding.UTF8.GetBytes(path));
                    codexFolder = ""; RenderCodex();
                    SetStatus("Папка для новых проектов выбрана.", false);
                } catch (Exception error) { SetStatus(error.Message, true); }
            }
        }
        private async Task ConnectCodex(bool signIn) {
            if (codexAuth != null || codexRun != null || !api.Account.SignedIn) return;
            string owner = api.Account.Email;
            codexOwner = owner;
            var cancellation = new CancellationTokenSource(TimeSpan.FromMinutes(signIn ? 5 : 1));
            codexAuth = cancellation;
            try {
                codexConnection = signIn ? "Ожидаю вход в ChatGPT…" : "Проверяю вход в Codex…";
                RenderCodex();
                string executable = RequireCodex();
                if (!await LocalCodex.ChatGptConnected(executable, store.Root, cancellation.Token)) {
                    if (signIn) await LocalCodex.SignIn(executable, store.Root, cancellation.Token);
                    else { if (codexOwner == owner) codexConnection = "Войдите в Codex через аккаунт ChatGPT."; return; }
                }
                if (codexOwner == owner && api.Account.Email == owner) {
                    codexExe = executable; SaveSettings(); codexConnection = "Аккаунт ChatGPT подключён.";
                }
            } catch (OperationCanceledException) {
                if (codexOwner == owner) codexConnection = "Подключение остановлено.";
            } catch (Exception error) {
                if (codexOwner == owner) codexConnection = error.Message;
            } finally {
                if (codexAuth == cancellation) codexAuth = null;
                cancellation.Dispose();
                if (!closed && openPanel == "Codex") RenderCodex();
            }
        }
        private async Task HandleCodexRequest(string input, CodexVoiceRequest request) {
            if (request.Action == "start" && request.Task.Length > 0) {
                await SubmitCodexTask(input, request.Task, CodexDevelopmentIntent.Match(request.Task, CurrentCodexProject() != null) == "new");
                return;
            }
            if (openPanel.Length > 0) ClosePanel();
            AddMessage("user", input);
            if (request.Action == "stop") {
                bool stopping = codexRun != null;
                StopCodex();
                await AnswerCodexStatus(stopping ? "Останавливаю Codex." : "Сейчас Codex свободен.");
            } else if (request.Action == "status") {
                await AnswerCodexStatus(codexState.Length > 0 && codexOwner == api.Account.Email ? codexState : "Сейчас Codex свободен.");
            } else {
                await AnswerCodexStatus("Скажите, что создать или изменить в проекте.");
            }
        }
        private async Task AnswerCodexStatus(string message) {
            AddMessage("assistant", message);
            SetStatus(message, false);
            if (autoSpeak && !busy && !speaking) await Safe(() => Speak(message, CancellationToken.None));
        }
        private async Task RequireCodexPro(CancellationToken cancellation) {
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation)) {
                deadline.CancelAfter(TimeSpan.FromSeconds(20));
                var development = await api.Get("/v1/development/projects", deadline.Token);
                if (!Json.Flag(development, "enabled")) throw new InvalidOperationException("Задачи разработки с Codex доступны в Тройке Pro.");
                if (Json.Rows(development, "projects").Count(project => !DevelopmentAutopilot.Terminal(Json.Text(project, "status"))) >= 4)
                    throw new InvalidOperationException("Уже работают четыре проекта разработки. Освободите место для задачи Codex.");
            }
        }
        private async Task SubmitCodexTask(string input, string task, bool newProject) {
            if (openPanel.Length > 0) ClosePanel();
            AddMessage("user", input);
            if (CodexVoiceRequest.TargetsChatGptProject(task)) { await AnswerCodexStatus(ChatGptProjectHelp); return; }
            if (task.Length == 0 || task.Length > 8000) { await AnswerCodexStatus("Задача для Codex должна содержать до 8000 символов."); return; }
            if (preview || !api.Account.SignedIn) return;
            string owner = api.Account.Email, conversation = api.SessionId;
            if (codexRun != null || codexAuth != null) {
                if (codexRun != null && !codexRun.IsCancellationRequested && !codexConfirming && !newProject && codexOwner == owner && codexSession == conversation && codexFollowups.Count < 4) {
                    codexFollowups.Enqueue(task);
                    await AnswerCodexStatus("Добавила задачу. Codex возьмёт её после текущей работы.");
                } else await AnswerCodexStatus("Codex сейчас занят. Можно продолжить разговор, пока он работает.");
                return;
            }
            await StartCodex(task, owner, conversation, newProject ? null : CurrentCodexProject());
        }
        private async Task StartCodex(string task, string owner, string conversation, CodexConversationLink project) {
            var cancellation = new CancellationTokenSource(TimeSpan.FromMinutes(40));
            codexOwner = owner; codexSession = conversation; codexConfirming = true; codexRun = cancellation;
            codexFolder = ""; codexFollowups.Clear();
            bool launched = false;
            try {
                UpdateCodexProgress("Проверяю доступ к Codex…");
                await RequireCodexPro(cancellation.Token);
                string executable = RequireCodex();
                using (var access = CancellationTokenSource.CreateLinkedTokenSource(cancellation.Token)) {
                    access.CancelAfter(TimeSpan.FromSeconds(20));
                    if (!await LocalCodex.ChatGptConnected(executable, store.Root, access.Token))
                        throw new InvalidOperationException("Войдите в Codex через аккаунт ChatGPT.");
                }
                cancellation.Token.ThrowIfCancellationRequested();
                if (!CodexOwnerCurrent(owner) || api.SessionId != conversation) return;
                if (project == null) {
                    string root = CodexProjectsRoot(owner);
                    string suggested = Path.Combine(root, "project-" + DateTime.Now.ToString("yyyyMMdd") + "-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                    LocalCodex.ValidateProject(root, suggested);
                    ShowFromTray();
                    await ReleaseWakeMicrophone();
                    if (!CodexOwnerCurrent(owner) || api.SessionId != conversation) return;
                    string folder = ConfirmCodexProject(task, suggested);
                    cancellation.Token.ThrowIfCancellationRequested();
                    if (!CodexOwnerCurrent(owner) || api.SessionId != conversation) return;
                    if (folder == null) { AddMessage("assistant", "Проект не запущен."); return; }
                    await RequireCodexPro(cancellation.Token);
                    if (!CodexOwnerCurrent(owner) || api.SessionId != conversation) return;
                    if (folder == suggested) Directory.CreateDirectory(folder);
                    LocalCodex.ValidateWorkspace(folder);
                    project = new CodexConversationLink(conversation, folder);
                    new CodexConversationStore(store, owner).Save(project);
                    RenderHistory();
                }
                codexFolder = project.Folder; codexConfirming = false; launched = true;
                UpdateCodexProgress("Передаю задачу Codex…");
                ShowCodexCard(project, codexState, cancellation);
                codexReports.Enqueue("Я передала задачу Кодексу. Мы можем продолжить разговор.");
                while (true) {
                    cancellation.Token.ThrowIfCancellationRequested();
                    var current = project;
                    bool reportedWork = false;
                    var progress = new Progress<string>(value => {
                        if (codexRun != cancellation || cancellation.IsCancellationRequested || !CodexOwnerCurrent(owner)) return;
                        UpdateCodexProgress(value);
                        if (!reportedWork && value == "Codex меняет файлы проекта") {
                            reportedWork = true; codexReports.Enqueue("Кодекс редактирует файлы проекта.");
                        }
                    });
                    var started = new Progress<string>(id => {
                        if (codexRun != cancellation || !CodexOwnerCurrent(owner)) return;
                        try { RememberCodexThread(owner, current.WithThread(id)); }
                        catch (Exception error) { SetStatus(error.Message, true); }
                    });
                    var result = await LocalCodex.RunInChat(executable, current, task,
                        ((IProgress<string>)progress).Report, ((IProgress<string>)started).Report, cancellation.Token);
                    if (!CodexOwnerCurrent(owner) || cancellation.IsCancellationRequested) return;
                    project = current.WithThread(result.ThreadId);
                    RememberCodexThread(owner, project);
                    UpdateCodexProgress("Codex завершил задачу.");
                    if (api.SessionId == conversation) {
                        if (result.Summary.Length > 0) AddMessage("assistant", result.Summary);
                        if (codexCard != null && codexCard.Run == cancellation) codexCard.Stop.Visibility = Visibility.Collapsed;
                    }
                    if (codexFollowups.Count == 0) break;
                    await RequireCodexPro(cancellation.Token);
                    cancellation.Token.ThrowIfCancellationRequested();
                    task = codexFollowups.Dequeue();
                    UpdateCodexProgress("Codex приступает к следующей задаче…");
                    if (api.SessionId == conversation) ShowCodexCard(project, codexState, cancellation);
                }
                codexReports.Enqueue("Кодекс завершил работу. Результат и ссылка на чат в разговоре Тройки.");
            } catch (OperationCanceledException) {
                if (CodexOwnerCurrent(owner)) UpdateCodexProgress(launched ? "Codex остановлен. Сохранённые файлы остались в папке проекта." : "Запуск Codex остановлен.");
                codexReports.Clear();
            } catch (Exception error) {
                if (!CodexOwnerCurrent(owner)) return;
                UpdateCodexProgress(error.Message);
                if (!launched && api.SessionId == conversation) AddMessage("assistant", error.Message);
                if (launched) codexReports.Enqueue("Кодекс не завершил задачу. Подробности в разговоре Тройки.");
                if (codexFollowups.Count > 0 && api.SessionId == conversation) AddMessage("assistant", "Задачи из очереди можно отправить снова после устранения ошибки.");
            } finally {
                codexConfirming = false;
                codexFollowups.Clear();
                if (codexRun == cancellation) codexRun = null;
                if (codexCard != null && codexCard.Run == cancellation) codexCard.Stop.Visibility = Visibility.Collapsed;
                cancellation.Dispose();
                if (!closed && openPanel == "Codex") RenderCodex();
            }
        }
        private string ConfirmCodexProject(string task, string folder) {
            var body = new StackPanel { Margin = new Thickness(20) };
            body.Children.Add(Label("Подключить папку к разговору?", 20, text));
            body.Children.Add(new TextBox { Text = task, IsReadOnly = true, TextWrapping = TextWrapping.Wrap, MaxHeight = 145, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(0, 12, 0, 8) });
            var path = Label(folder, 13, text);
            body.Children.Add(path);
            body.Children.Add(Label("Codex сможет менять файлы в этой папке. Следующие задачи разработки в этом разговоре продолжат тот же чат Codex.", 12, muted));
            var dialog = new Window { Owner = this, Title = "Рабочая папка Codex", Content = body, Width = 520,
                SizeToContent = SizeToContent.Height, WindowStartupLocation = WindowStartupLocation.CenterOwner,
                ResizeMode = ResizeMode.NoResize, Background = background };
            body.Children.Add(Button("Выбрать существующую папку…", () => {
                using (var picker = new System.Windows.Forms.FolderBrowserDialog { Description = "Выберите папку проекта для этого разговора", ShowNewFolderButton = false }) {
                    if (picker.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;
                    try { path.Text = LocalCodex.ValidateWorkspace(picker.SelectedPath); }
                    catch (Exception error) { MessageBox.Show(dialog, error.Message, "Рабочая папка Codex"); }
                }
            }, false));
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 16, 0, 0) };
            buttons.Children.Add(Button("Подключить и запустить", () => dialog.DialogResult = true, true));
            var cancel = Button("Отмена", () => dialog.DialogResult = false, false); cancel.IsCancel = true;
            buttons.Children.Add(cancel); body.Children.Add(buttons);
            return dialog.ShowDialog() == true ? path.Text : null;
        }
        private void UpdateCodexProgress(string value) {
            codexState = value;
            if (codexProgressLabel != null) codexProgressLabel.Text = value;
            if (codexCard != null && codexCard.Run == codexRun) codexCard.Status.Text = value;
            if (!busy && !speaking && !recorder.Recording && !wakeRecording && !closed && api.SessionId == codexSession) SetStatus(value, false);
        }
        private void StopCodex() {
            if (codexRun == null) return;
            codexReports.Clear(); codexFollowups.Clear();
            codexRun.Cancel();
            UpdateCodexProgress("Останавливаю Codex…");
        }
        private async Task SpeakCodexReport() {
            if (codexReports.Count == 0 || projectSpeech != null || !api.Account.SignedIn || codexOwner != api.Account.Email) return;
            if (!autoSpeak || !Autopilot.VoiceReports) { codexReports.Clear(); return; }
            if (closed || busy || speaking || recorder.Recording || wakeRecording || wakeLocked || wakeSuspended || voiceEnrollment || pendingApproval != null || codexConfirming) return;
            var message = codexReports.Dequeue();
            using (var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(45))) {
                projectSpeech = cancellation;
                try {
                    await ReleaseWakeMicrophone();
                    var bytes = await api.Speech(message, cancellation.Token);
                    try {
                        if (!busy && !speaking && !recorder.Recording && codexOwner == api.Account.Email && !closed)
                            await PlayPhrase(bytes, cancellation.Token);
                    } finally { Array.Clear(bytes, 0, bytes.Length); }
                } catch { /* Project progress remains visible without speech. */ }
                finally { if (projectSpeech == cancellation) projectSpeech = null; }
            }
        }
        private void DisposeCodex() {
            codexTimer.Stop();
            ResetCodexAccount();
        }
    }
}
