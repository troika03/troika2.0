using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Runtime.InteropServices;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private string projectFolder = "";
        private CheckReport checkReport;
        private CancellationTokenSource localCheck;
        [DllImport("user32.dll")] private static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
        private string TryLocalAction(string input) {
            var command = input.Trim().TrimEnd('.', '!', '?').ToLowerInvariant();
            string executable = null, argument = "";
            if (command == "открой калькулятор" || command == "запусти калькулятор") executable = "calc.exe";
            else if (command == "открой блокнот" || command == "запусти блокнот") executable = "notepad.exe";
            else if (command == "открой документы" || command == "открой папку документы") { executable = "explorer.exe"; argument = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments); }
            if (executable != null) { Process.Start(new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", executable), argument.Length == 0 ? "" : "\"" + argument + "\"") { UseShellExecute = true }); return "Открыто на этом компьютере."; }
            if (command == "открой настройки звука") { Process.Start(new ProcessStartInfo("ms-settings:sound") { UseShellExecute = true }); return "Настройки звука открыты."; }
            byte media = command == "громче" ? (byte)0xAF : command == "тише" ? (byte)0xAE : command == "пауза музыки" || command == "продолжи музыку" ? (byte)0xB3 : command == "следующий трек" ? (byte)0xB0 : (byte)0;
            if (media != 0) { keybd_event(media, 0, 0, UIntPtr.Zero); keybd_event(media, 0, 2, UIntPtr.Zero); return "Команда передана Windows."; }
            return null;
        }
        private void Prepare(string prompt) { ClosePanel(); composer.Text = prompt; composer.Focus(); composer.CaretIndex = composer.Text.Length; }
        private void RenderCapabilities() {
            panelContent.Children.Clear();
            panelContent.Children.Add(Label("Скажите задачу — или выберите действие", 14, muted)); Gap();
            var cards = CapabilityCards();
            AddCapabilityCard(cards, "Навыки и плагины", "Каталог инструментов Тройки", "spark", () => OpenPanel("Каталог возможностей"));
            AddCapabilityCard(cards, "Поиск и сравнение", "Информация и источники", "spark", () => Prepare("Найди через веб-поиск и сравни "));
            AddCapabilityCard(cards, "Документ DOCX", "Текст и таблицы", "files", () => Prepare("Создай DOCX: "));
            AddCapabilityCard(cards, "Документ PDF", "Готовый документ", "files", () => Prepare("Создай PDF: "));
            AddCapabilityCard(cards, "Презентация PPTX", "Слайды для вашей задачи", "files", () => Prepare("Создай PPTX: "));
            AddCapabilityCard(cards, "Разработка", "Создание и проверка кода", "code", () => OpenPanel("Разработка"));
            AddCapabilityCard(cards, "Проекты и дела", "Задачи и напоминания", "tasks", () => OpenPanel("Дела"));
            AddCapabilityCard(cards, "Файлы на этом ПК", "Сохранённые результаты", "files", () => OpenPanel("Файлы"));
            AddCapabilityCard(cards, "Память", "Посмотреть и изменить", "memory", () => OpenPanel("Память"));
            AddCapabilityCard(cards, "Профиль", "Аккаунт, тариф и устройства", "profile", () => OpenPanel("Аккаунт"));
            panelContent.Children.Add(cards); Gap();
            panelContent.Children.Add(Label("Действия на ПК", 16, text));
            Gap(); var local = CapabilityCards();
            AddCapabilityCard(local, "Калькулятор", "Открыть приложение", "tasks", () => LaunchFixed("calc.exe", ""));
            AddCapabilityCard(local, "Блокнот", "Открыть приложение", "files", () => LaunchFixed("notepad.exe", ""));
            AddCapabilityCard(local, "Папка Документы", "Открыть в Проводнике", "files", () => LaunchFixed("explorer.exe", Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)));
            AddCapabilityCard(local, "Звук и микрофон", "Настройки Windows", "spark", () => LaunchUri("ms-settings:sound"));
            panelContent.Children.Add(local);
            Gap(); panelContent.Children.Add(Label("Просмотр экрана и управление другими приложениями требуют отдельной интеграции и пока недоступны в новом клиенте.", 11, muted));
        }
        private void LaunchFixed(string executable, string argument) { try { Process.Start(new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", executable), argument.Length == 0 ? "" : "\"" + argument + "\"") { UseShellExecute = true }); SetStatus("Открыто", false); } catch { SetStatus("Windows не смогла открыть приложение.", true); } }
        private void LaunchUri(string uri) { try { Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true }); } catch { SetStatus("Не удалось открыть настройки Windows.", true); } }
        private void RenderSources(Dictionary<string, object> activity, StackPanel target, HashSet<string> seen) {
            foreach (var source in Json.Rows(activity, "sources")) {
                var url = Json.Text(source, "url"); Uri uri;
                if (url.Length > 2048 || !Uri.TryCreate(url, UriKind.Absolute, out uri) || (uri.Scheme != "https" && uri.Scheme != "http") || uri.UserInfo.Length > 0 || seen.Count >= 20 || !seen.Add(url)) continue;
                var title = Json.Text(source, "title"); if (title.Length == 0) title = uri.Host; if (title.Length > 110) title = title.Substring(0, 110) + "…";
                var state = Json.Text(source, "status"); var stateText = state == "read" ? "Прочитано" : state == "opening" ? "Открываю" : state == "failed" ? "Ошибка чтения" : "Найдено";
                var button = Button(title + "\n" + uri.Host + " · " + stateText, () => OpenWeb(url), false); button.Content = Label(title + "\n" + uri.Host + " · " + stateText, 12, muted); button.MaxWidth = 360; button.HorizontalAlignment = HorizontalAlignment.Left; button.Margin = new Thickness(0, 0, 0, 6); target.Children.Add(button);
            }
        }
        private async Task ExportAccount() {
            var picker = new Microsoft.Win32.SaveFileDialog { FileName = "Troika-account-export.zip", DefaultExt = ".zip", Filter = "Экспорт ZIP|*.zip", OverwritePrompt = true };
            if (picker.ShowDialog(this) != true) return;
            await Safe(async () => { var bytes = await api.Download("/v1/account/export", 50 * 1024 * 1024, CancellationToken.None); LocalStore.WriteAtomic(picker.FileName, bytes); SetStatus("Экспорт аккаунта сохранён", false); });
        }
        private void ConfirmAccountDeletion() {
            if (busy || recorder.Recording || speaking || localCheck != null) { SetStatus("Сначала остановите текущую задачу.", true); return; }
            panelContent.Children.Clear(); panelContent.Children.Add(Label("Удалить аккаунт на всех устройствах?", 19, text)); Gap();
            panelContent.Children.Add(Label("История, память и дела будут удалены с сервера. Устройства потеряют доступ. Восстановить удалённые данные нельзя. Локальные готовые файлы останутся на ПК.", 13, muted)); Gap();
            panelContent.Children.Add(Label("Введите «УДАЛИТЬ»", 12, muted)); var confirmation = Field("Подтверждение удаления аккаунта", false); panelContent.Children.Add(confirmation);
            AddPanelButton("Удалить аккаунт", () => { var task = Safe(async () => { if (confirmation.Text != "УДАЛИТЬ") throw new InvalidOperationException("Для удаления введите «УДАЛИТЬ»."); await api.Call("DELETE", "/v1/account", new { confirmation = "DELETE_MY_ACCOUNT" }, CancellationToken.None); ResetDevelopmentState(); store.ForgetSession(); api.Account = new AccountSession(); api.SessionId = ""; transcript.Children.Clear(); sessions.Clear(); ShowHero(); RenderHistory(); profile.Content = "Войти"; await RenderAccount(); SetStatus("Аккаунт удалён или поставлен в очередь удаления. Доступ отозван.", false); }); }, true);
            AddPanelButton("Отмена", () => OpenPanel("Аккаунт"), false);
            SurfaceGroup(0, "Удаление аккаунта", "", "profile");
        }
        private void ConfirmDeviceRevocation(string id, string name) {
            panelContent.Children.Clear(); panelContent.Children.Add(Label("Отозвать доступ устройства «" + name + "»?", 18, text)); Gap(); panelContent.Children.Add(Label("Устройство потеряет доступ к аккаунту. История и память сохранятся.", 13, muted));
            AddPanelButton("Отозвать", () => { var task = Safe(async () => { await api.Call("DELETE", "/v1/account/devices/" + Uri.EscapeDataString(id), null, CancellationToken.None); await ShowDevices(); }); }, true); AddPanelButton("Отмена", () => { var task = ShowDevices(); }, false);
            SurfaceGroup(0, "Доступ устройства", "", "profile");
        }
        private void EditMemory(Dictionary<string, object> memory) {
            panelContent.Children.Clear();
            var title = Field("Название записи", false); var content = Field("Содержимое записи", true); if (memory != null) { title.Text = Json.Text(memory, "title"); content.Text = Json.Text(memory, "content"); } panelContent.Children.Add(Label("Название", 12, muted)); panelContent.Children.Add(title); panelContent.Children.Add(Label("Что запомнить", 12, muted)); panelContent.Children.Add(content);
            int actions = panelContent.Children.Count; AddPanelButton("Сохранить", () => { var task = Safe(async () => { if (title.Text.Trim().Length < 2 || content.Text.Trim().Length < 2) throw new InvalidOperationException("Введите название и содержимое записи."); await api.Call(memory == null ? "POST" : "PATCH", memory == null ? "/v1/memories" : "/v1/memories/" + Uri.EscapeDataString(Json.Text(memory, "id")), new { title = title.Text.Trim(), content = content.Text.Trim() }, CancellationToken.None); await OpenPanelTask("Память"); }); }, true); AddPanelButton("Отмена", () => OpenPanel("Память"), false); CompactActions(actions); SurfaceGroup(0, memory == null ? "Новая запись памяти" : "Изменить запись памяти", "Запись будет доступна на телефоне и ПК.", "memory");
        }
        private async Task ShowLegacyFiles() {
            await Safe(async () => {
                var owner = api.Account.Email; var value = await api.Get("/v1/artifacts", CancellationToken.None); if (api.Account.Email != owner) return;
                panelContent.Children.Clear(); panelContent.Children.Add(Label("Старые серверные файлы", 17, text)); Gap(); var items = Json.Rows(value, "data").ToList();
                if (items.Count == 0) panelContent.Children.Add(Label("Серверных файлов нет.", 13, muted));
                foreach (var item in items) { int fileCard = panelContent.Children.Count; var file = item; AddPanelButton("Сохранить на этот ПК", () => { var task = Safe(async () => {
                        var id = Json.Text(file, "id"); var name = LocalStore.SafeName(Json.Text(file, "filename")); var bytes = await api.Download("/v1/artifacts/" + Uri.EscapeDataString(id) + "/download", 50 * 1024 * 1024, CancellationToken.None);
                        if (bytes.Length != Json.Number(file, "size")) throw new InvalidDataException("Размер файла не совпадает."); if (api.Account.Email != owner) throw new InvalidOperationException("Аккаунт изменился. Получение отменено.");
                        var path = Path.Combine(store.FilesFolder(owner), "delivery_" + LocalStore.Hash(System.Text.Encoding.UTF8.GetBytes(id)).Substring(0, 32), name); LocalStore.WriteAtomic(path, bytes); SetStatus("Файл сохранён на этом ПК. Серверный оригинал сохранён.", false); await OpenPanelTask("Файлы");
                    }); }, false); SurfaceGroup(fileCard, Json.Text(item, "filename"), "Серверный оригинал сохранится.", "files"); }
                AddPanelButton("Назад к локальным файлам", () => OpenPanel("Файлы"), false);
            });
        }
        private async Task EnsureProject() {
            var value = await api.Get("/v1/assistant/projects", CancellationToken.None); var items = Json.Rows(value, "projects").ToList();
            if (items.Any(item => Json.Flag(item, "is_active"))) return;
            if (items.Count == 0) { await api.Call("POST", "/v1/assistant/projects", new { name = "Личные дела" }, CancellationToken.None); return; }
            await api.Call("PUT", "/v1/assistant/projects/" + Uri.EscapeDataString(Json.Text(items[0], "id")) + "/active", null, CancellationToken.None);
        }
        private void RenderProjects(Dictionary<string, object> value) {
            var items = Json.Rows(value, "projects").ToList();
            var selection = new ComboBox { Margin = new Thickness(0, 7, 0, 8) }; AccessibleName(selection, "Текущий проект");
            foreach (var item in items) { var row = new ComboBoxItem { Content = Json.Text(item, "name"), Tag = Json.Text(item, "id") }; selection.Items.Add(row); if (Json.Flag(item, "is_active")) selection.SelectedItem = row; }
            selection.SelectionChanged += async delegate { if (selection.SelectedItem == null) return; var id = Convert.ToString(((ComboBoxItem)selection.SelectedItem).Tag); await Safe(async () => { await api.Call("PUT", "/v1/assistant/projects/" + Uri.EscapeDataString(id) + "/active", null, CancellationToken.None); }); }; panelContent.Children.Add(selection);
            AddPanelButton("Создать проект", () => {
                panelContent.Children.Clear(); var name = Field("Название проекта", false); panelContent.Children.Add(name); int actions = panelContent.Children.Count; AddPanelButton("Создать", () => { var task = Safe(async () => { if (name.Text.Trim().Length < 2) throw new InvalidOperationException("Введите название проекта."); await api.Call("POST", "/v1/assistant/projects", new { name = name.Text.Trim() }, CancellationToken.None); await OpenPanelTask("Дела"); }); }, true); AddPanelButton("Отмена", () => OpenPanel("Дела"), false); CompactActions(actions); SurfaceGroup(0, "Новый проект", "Дайте название группе задач и заметок.", "files");
            }, false);
            var create = (Button)panelContent.Children[panelContent.Children.Count - 1]; panelContent.Children.Remove(create); panelContent.Children.Remove(selection);
            var controls = new Grid(); controls.ColumnDefinitions.Add(new ColumnDefinition()); controls.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); selection.Margin = new Thickness(0, 0, 10, 0); create.Margin = new Thickness(0); Grid.SetColumn(create, 1); controls.Children.Add(selection); controls.Children.Add(create); panelContent.Children.Add(controls);
        }
        private async Task ShowNotes() {
            await Safe(async () => {
                await EnsureProject(); var value = await api.Get("/v1/assistant/notes", CancellationToken.None); panelContent.Children.Clear();
                var title = Field("Название заметки", false); var content = Field("Текст заметки", true); panelContent.Children.Add(Label("Название", 12, muted)); panelContent.Children.Add(title); panelContent.Children.Add(Label("Текст заметки", 12, muted)); panelContent.Children.Add(content);
                AddPanelButton("Сохранить заметку", () => { var task = Safe(async () => { await api.Call("POST", "/v1/assistant/notes", new { content = (title.Text.Trim().Length == 0 ? "" : title.Text.Trim() + "\n") + content.Text, kind = "context" }, CancellationToken.None); await ShowNotes(); }); }, true); SurfaceGroup(0, "Новая заметка", "Контекст для текущего проекта", "files");
                foreach (var note in Json.Rows(value, "notes")) { int noteCard = panelContent.Children.Count; panelContent.Children.Add(Label(Json.Text(note, "content"), 13, muted)); SurfaceGroup(noteCard, Json.Text(note, "title"), "", "files"); } AddPanelButton("Назад к делам", () => OpenPanel("Дела"), false);
            });
        }
        private void RenderDevelopment() {
            panelContent.Children.Clear();
            if (localCheck != null || developmentRelay != null && developmentRelay.Checking) { panelContent.Children.Add(Label("Разработка или проверка выполняется…", 13, muted)); AddPanelButton("Остановить", () => { var task = Stop(); }, true); return; }
            panelContent.Children.Add(Label("Что разработать?", 12, muted));
            var request = Field("Какой проект создать", true); request.Text = developmentRequest; request.TextChanged += delegate { developmentRequest = request.Text; }; request.MinHeight = 84; panelContent.Children.Add(request);
            panelContent.Children.Add(Label("Способ проверки", 12, muted)); var kinds = new ComboBox { Margin = new Thickness(0, 8, 0, 8) }; AccessibleName(kinds, "Способ проверки проекта");
            foreach (var kind in new[] { DevelopmentWorkflow.ModelReview, "Python: тесты", "JavaScript: тесты", "Python: синтаксис", "JavaScript: синтаксис" }) kinds.Items.Add(kind); kinds.SelectedIndex = 0; panelContent.Children.Add(kinds);
            AddPanelButton("Разработать проект", () => { var task = ChooseDevelopmentTarget(developmentRequest, Convert.ToString(kinds.SelectedItem), false); }, true);
            panelContent.Children.Add(Label("Запуская автопилот, вы подтверждаете предел 250 000 AI-токенов из месячного остатка. Спишется фактический расход; превышение потребует подтверждения.", 11, muted));
            SurfaceGroup(0, "От идеи до проекта", "Тройка пишет код и проверяет исходники моделью через API. Тесты запускаются отдельно.", "code"); int imported = panelContent.Children.Count;
            Check("Голосовые отчёты по проектам", Autopilot.VoiceReports, enabled => { Autopilot.SetVoice(enabled); if (!enabled && projectSpeech != null) projectSpeech.Cancel(); });
            panelContent.Children.Add(Label("Важные этапы и результат. Во время разговора Тройка подождёт.", 11, muted));
            autopilotCards = new StackPanel(); panelContent.Children.Add(autopilotCards); ObserveAutopilot(); RenderAutopilotCards();
            Check("Принимать проверки с телефона", developmentRelay != null && developmentRelay.Enabled, enabled => { var task = ToggleDevelopmentWorker(enabled); });
            panelContent.Children.Add(Label("ПК появится на телефоне, пока этот раздел открыт и приём включён. Первый запуск подтверждается здесь.", 11, muted));
            AddPanelButton("Открыть ZIP с исходниками…", () => {
                if (developmentRelay != null && developmentRelay.Checking) return;
                var picker = new Microsoft.Win32.OpenFileDialog { Filter = "Проект ZIP|*.zip", InitialDirectory = api.Account.Email.Length == 0 ? Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments) : store.FilesFolder(api.Account.Email) };
                if (picker.ShowDialog(this) == true) { try { projectFolder = Development.Extract(picker.FileName, Path.Combine(store.FilesFolder(api.Account.Email), "projects")); checkReport = null; RenderDevelopment(); } catch (Exception error) { SetStatus(error.Message, true); } }
            }, false); SurfaceGroup(imported, "Готовые исходники и телефон", "Откройте ZIP или примите проверку с телефона.", "files");
            if (projectFolder.Length == 0) return;
            int project = panelContent.Children.Count;
            panelContent.Children.Add(Label("Исходники распакованы в новую папку. Оригинал сохранён.", 11, muted));
            AddPanelButton("Открыть папку проекта", () => { try { Process.Start(new ProcessStartInfo(projectFolder) { UseShellExecute = true }); } catch { SetStatus("Не удалось открыть папку.", true); } }, false); int checks = panelContent.Children.Count;
            var modelReportPath = Path.Combine(projectFolder, "MODEL_REVIEW.md");
            if (File.Exists(modelReportPath)) {
                panelContent.Children.Add(Label("Ревью модели — код и тесты не запускались", 12, muted));
                var modelReport = Field("Ревью модели", true); modelReport.IsReadOnly = true; modelReport.Text = File.ReadAllText(modelReportPath); modelReport.MaxHeight = 180; modelReport.FontSize = 12; panelContent.Children.Add(modelReport);
            }
            AddPanelButton("Проверить моделью и исправить", () => { var task = ReviewExistingDevelopment(); }, false);
            foreach (var kind in new[] { "Python: синтаксис", "Python: тесты", "JavaScript: синтаксис", "JavaScript: тесты" }) {
                var selectedKind = kind; AddPanelButton(kind, () => ConfirmCheck(selectedKind), false);
            }
            CompactActions(checks); SurfaceGroup(project, Path.GetFileName(projectFolder), "", "code");
            if (checkReport != null) {
                int result = panelContent.Children.Count; panelContent.Children.Add(Label("Код завершения: " + checkReport.ExitCode, 12, muted));
                var report = Field("Отчёт проверки", true); report.IsReadOnly = true; report.Text = checkReport.Output; report.MaxHeight = 180; report.FontSize = 12; panelContent.Children.Add(report);
                AddPanelButton("Исправить и проверить", () => { var task = ChooseDevelopmentTarget(Development.RepairContext(projectFolder, checkReport), checkReport.Kind, true); }, true);
                SurfaceGroup(result, checkReport.Verified ? "Проверка прошла" : "Проверка не подтвердила результат", "", "code");
            }
        }
        private void ConfirmCheck(string kind) {
            if (localCheck != null || developmentRelay != null && developmentRelay.Checking) return;
            panelContent.Children.Clear(); panelContent.Children.Add(Label("Запустить «" + kind + "»?", 18, text)); Gap();
            panelContent.Children.Add(Label("Папка: " + Path.GetFileName(projectFolder) + ". Проверка запускает код с вашими правами Windows. Выполняйте только доверенные проекты. Лимит — 90 секунд.", 13, muted)); Gap();
            AddPanelButton("Разрешить запуск", () => { var task = ExecuteCheck(kind); }, true); AddPanelButton("Отмена", () => OpenPanel("Разработка"), false);
            SurfaceGroup(0, "Подтверждение проверки", "", "code");
        }
        private async Task ExecuteCheck(string kind) {
            if (localCheck != null) return; localCheck = new CancellationTokenSource(); panelContent.Children.Clear(); panelContent.Children.Add(Label("Проверяю проект на этом ПК…", 16, text)); AddPanelButton("Остановить проверку", () => localCheck.Cancel(), true);
            await Safe(async () => { checkReport = await Development.Check(projectFolder, kind, localCheck.Token); }); localCheck.Dispose(); localCheck = null; if (!closed && openPanel == "Разработка") RenderDevelopment();
        }
    }
}
