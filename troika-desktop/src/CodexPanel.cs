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
        private string codexExe = "", codexOwner = "", codexFolder = "", codexDraft = "";
        private string codexState = "", codexResult = "", codexConnection = "";
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
            codexOwner = ""; codexFolder = ""; codexDraft = ""; codexState = ""; codexResult = ""; codexConnection = "";
            codexReports.Clear();
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
            panelContent.Children.Add(Label("Локальный Codex", 22, text));
            panelContent.Children.Add(Label("Задачи выполняются на этом ПК через ваш вход в ChatGPT. Доступно в Pro.", 13, muted));
            if (codexConnection.Length > 0) panelContent.Children.Add(Label(codexConnection, 13, text));
            if (codexAuth == null && codexRun == null && !codexConfirming) {
                AddPanelButton("Проверить подключение", () => { var pending = ConnectCodex(false); }, false);
                AddPanelButton("Войти через ChatGPT", () => { var pending = ConnectCodex(true); }, false);
                AddPanelButton("Выбрать codex.exe…", ChooseCodexExecutable, false);
            } else if (codexAuth != null) AddPanelButton("Отменить вход", () => codexAuth.Cancel(), false);
            Gap();
            codexProgressLabel = Label(codexState, 14, text);
            panelContent.Children.Add(codexProgressLabel);
            if (codexFolder.Length > 0) AddPanelButton("Открыть папку проекта", () => OpenCodexFolder(codexFolder), false);
            if (codexResult.Length > 0) panelContent.Children.Add(Label(codexResult, 13, text));
            if (codexRun != null) {
                AddPanelButton("Остановить Codex", StopCodex, true);
                return;
            }
            if (codexConfirming) return;
            var root = CodexProjectsRoot(api.Account.Email);
            AddPanelButton("Выбрать папку для проектов…", ChooseCodexProjectsLocation, false);
            var projects = new ComboBox { Margin = new Thickness(0, 8, 0, 8) };
            AccessibleName(projects, "Папка проекта Codex");
            projects.Items.Add(new ComboBoxItem { Content = "Новый проект", Tag = "" });
            if (Directory.Exists(root)) {
                foreach (string path in Directory.EnumerateDirectories(root, "project-*").OrderByDescending(p => p).Take(30)) {
                    try { LocalCodex.ValidateProject(root, path); }
                    catch (InvalidOperationException) { continue; }
                    projects.Items.Add(new ComboBoxItem { Content = Path.GetFileName(path), Tag = path });
                }
            }
            projects.SelectedItem = projects.Items.Cast<ComboBoxItem>().FirstOrDefault(item => (string)item.Tag == codexFolder) ?? projects.Items[0];
            panelContent.Children.Add(projects);
            var request = Field("Задача для Codex", true);
            request.MaxLength = 8000;
            request.Text = codexDraft;
            request.TextChanged += delegate { codexDraft = request.Text; };
            panelContent.Children.Add(request);
            AddPanelButton("Передать задачу Codex", () => {
                var selection = projects.SelectedItem as ComboBoxItem;
                var pending = StartCodex(request.Text, selection == null ? "" : (string)selection.Tag);
            }, true);
            panelContent.Children.Add(Label("Из разговора: «Попроси Кодекс сделать проект…» или «Что делает Кодекс?»", 12, muted));
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
                    string path = LocalFileAccess.ValidateRoot(picker.SelectedPath);
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
            AddMessage("user", input);
            if (request.Action == "stop") {
                bool stopping = codexRun != null;
                StopCodex();
                await AnswerCodexStatus(stopping ? "Останавливаю Codex." : "Сейчас Codex свободен.");
                return;
            }
            if (request.Action == "status") {
                await AnswerCodexStatus(codexState.Length > 0 && codexOwner == api.Account.Email ? codexState : "Сейчас Codex свободен.");
                return;
            }
            if (CodexVoiceRequest.TargetsChatGptProject(request.Task)) {
                await AnswerCodexStatus(ChatGptProjectHelp);
                return;
            }
            if (codexRun != null || codexConfirming) {
                await AnswerCodexStatus("Codex уже занят. Пока проект выполняется, мы можем продолжить разговор.");
                return;
            }
            codexDraft = request.Task;
            if (request.Task.Length == 0) { ShowFromTray(); await OpenPanelTask("Codex"); return; }
            await StartCodex(request.Task, "");
        }
        private async Task AnswerCodexStatus(string message) {
            AddMessage("assistant", message);
            SetStatus(message, false);
            if (autoSpeak) await Safe(() => Speak(message, CancellationToken.None));
        }
        private async Task StartCodex(string task, string selectedFolder) {
            task = task.Trim();
            if (task.Length == 0 || task.Length > 8000) { SetStatus("Опишите задачу для Codex. До 8000 символов.", true); return; }
            if (CodexVoiceRequest.TargetsChatGptProject(task)) { SetStatus(ChatGptProjectHelp, true); return; }
            if (codexRun != null || codexAuth != null || codexConfirming || preview) return;
            if (!api.Account.SignedIn) { ShowFromTray(); await OpenPanelTask("Аккаунт"); return; }
            string owner = api.Account.Email;
            string root = CodexProjectsRoot(owner);
            string folder = selectedFolder.Length == 0 ? Path.Combine(root, "project-" + DateTime.Now.ToString("yyyyMMdd") + "-" + Guid.NewGuid().ToString("N").Substring(0, 8)) : selectedFolder;
            var cancellation = new CancellationTokenSource(TimeSpan.FromMinutes(40));
            bool launched = false, showSetup = false;
            codexOwner = owner; codexConfirming = true;
            codexRun = cancellation;
            try {
                string executable = RequireCodex();
                LocalCodex.ValidateProject(root, folder);
                using (var access = CancellationTokenSource.CreateLinkedTokenSource(cancellation.Token)) {
                    access.CancelAfter(TimeSpan.FromSeconds(20));
                    var development = await api.Get("/v1/development/projects", access.Token);
                    if (!Json.Flag(development, "enabled")) throw new InvalidOperationException("Разработка с Codex доступна в Pro.");
                    if (!await LocalCodex.ChatGptConnected(executable, store.Root, access.Token))
                        throw new InvalidOperationException("Войдите в Codex через аккаунт ChatGPT.");
                }
                cancellation.Token.ThrowIfCancellationRequested();
                if (api.Account.Email != owner || !api.Account.SignedIn || closed) return;
                ShowFromTray();
                await ReleaseWakeMicrophone();
                if (!ConfirmCodexTask(task, folder)) return;
                cancellation.Token.ThrowIfCancellationRequested();
                if (api.Account.Email != owner || !api.Account.SignedIn || closed) return;
                if (selectedFolder.Length > 0 && !Directory.Exists(folder)) throw new DirectoryNotFoundException("Папка этого проекта больше недоступна.");
                Directory.CreateDirectory(folder);
                LocalCodex.ValidateProject(root, folder);
                launched = true; codexConfirming = false;
                codexDraft = ""; codexResult = ""; codexFolder = folder;
                UpdateCodexProgress("Тройка передала задачу Codex.");
                codexReports.Enqueue("Я передала задачу Кодексу. Мы можем продолжить разговор.");
                if (openPanel == "Codex") RenderCodex();
                bool reportedWork = false;
                var progress = new Progress<string>(value => {
                    if (codexRun != cancellation || cancellation.IsCancellationRequested || codexOwner != owner) return;
                    UpdateCodexProgress(value);
                    if (!reportedWork && value == "Codex меняет файлы проекта") {
                        reportedWork = true; codexReports.Enqueue("Кодекс редактирует файлы проекта.");
                    }
                });
                var result = await LocalCodex.Run(executable, root, folder, task, ((IProgress<string>)progress).Report, cancellation.Token);
                if (codexOwner != owner || closed || cancellation.IsCancellationRequested) return;
                codexResult = result.Summary;
                var hasFiles = Directory.EnumerateFileSystemEntries(folder).Any();
                UpdateCodexProgress(hasFiles ? "Codex завершил задачу. Результат в папке проекта." : "Codex завершил задачу. Папка проекта пуста.");
                codexReports.Enqueue(hasFiles ? "Кодекс закончил задачу. Результат сохранён на компьютере." : "Кодекс закончил задачу. Отчёт в разделе разработки.");
            } catch (OperationCanceledException) {
                if (codexOwner == owner && launched) {
                    UpdateCodexProgress("Codex остановлен. Сохранённые файлы остались в папке проекта.");
                    codexReports.Clear();
                }
            } catch (Exception error) {
                if (codexOwner != owner || closed) return;
                UpdateCodexProgress(error.Message);
                if (launched) codexReports.Enqueue("Кодекс не завершил задачу. Подробности в разделе разработки.");
                else showSetup = true;
            } finally {
                codexConfirming = false;
                if (codexRun == cancellation) codexRun = null;
                cancellation.Dispose();
                if (!closed && openPanel == "Codex") RenderCodex();
            }
            if (showSetup) { ShowFromTray(); await OpenPanelTask("Codex"); }
        }
        private bool ConfirmCodexTask(string task, string folder) {
            var body = new StackPanel { Margin = new Thickness(20) };
            body.Children.Add(Label("Передать задачу Codex?", 20, text));
            body.Children.Add(new TextBox { Text = task, IsReadOnly = true, TextWrapping = TextWrapping.Wrap, MaxHeight = 175, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(0, 12, 0, 8) });
            body.Children.Add(Label("Рабочая папка", 12, muted));
            body.Children.Add(Label(folder, 13, text));
            body.Children.Add(Label("Codex сможет изменить файлы и запустить проверки внутри этой папки.", 12, muted));
            var dialog = new Window { Owner = this, Title = "Запуск Codex", Content = body, Width = 520,
                SizeToContent = SizeToContent.Height, WindowStartupLocation = WindowStartupLocation.CenterOwner,
                ResizeMode = ResizeMode.NoResize, Background = background };
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 16, 0, 0) };
            buttons.Children.Add(Button("Запустить в фоне", () => dialog.DialogResult = true, true));
            var cancel = Button("Отмена", () => dialog.DialogResult = false, false); cancel.IsCancel = true;
            buttons.Children.Add(cancel); body.Children.Add(buttons);
            return dialog.ShowDialog() == true;
        }
        private void OpenCodexFolder(string folder) {
            try {
                LocalCodex.ValidateProject(CodexProjectsRoot(api.Account.Email), folder);
                Process.Start(new ProcessStartInfo(folder) { UseShellExecute = true });
            } catch (Exception error) { SetStatus(error.Message, true); }
        }
        private void UpdateCodexProgress(string value) {
            codexState = value;
            if (codexProgressLabel != null) codexProgressLabel.Text = value;
            if (!busy && !speaking && !recorder.Recording && !wakeRecording && !closed) SetStatus(value, false);
        }
        private void StopCodex() {
            if (codexRun == null) return;
            codexReports.Clear();
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
