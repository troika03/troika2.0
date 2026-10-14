using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private DevelopmentRelay developmentRelay;
        private string developmentRequest = "";
        private TaskCompletionSource<bool> developmentConsent;
        private DevelopmentRelay Relay { get { return developmentRelay ?? (developmentRelay = new DevelopmentRelay(api)); } }
        private async Task ReviewExistingDevelopment() {
            await Safe(async () => {
                var sources = Development.Sources(projectFolder); sources.Remove("troika-project.json");
                await StartAutopilot("Сохрани функции проекта, проверь и исправь ошибки.", sources);
            });
        }
        private void ResetDevelopmentState() { if (localCheck != null) localCheck.Cancel(); if (developmentConsent != null) developmentConsent.TrySetResult(false); projectFolder = ""; checkReport = null; developmentRequest = ""; }
        private async Task ChooseDevelopmentTarget(string request, string kind, bool repair) {
            if (kind == DevelopmentWorkflow.ModelReview) { await StartAutopilot(request); return; }
            if (busy || localCheck != null || developmentRelay != null && developmentRelay.Checking) return;
            if (!api.Account.SignedIn) { await OpenPanelTask("Аккаунт"); SetStatus("Войдите для разработки.", true); return; }
            if (request.Trim().Length == 0) { SetStatus("Опишите проект.", true); return; }
            int revision = panelRevision; panelContent.Children.Clear(); panelContent.Children.Add(Label("Где проверять код?", 18, text)); Gap();
            panelContent.Children.Add(Label("До трёх исправлений по реальным ошибкам. Каждая новая версия использует запрос тарифа. Код на ПК получает ваши права Windows. Синтаксис не проверяет поведение программы.", 12, muted)); Gap();
            AddPanelButton("На этом ПК", () => { var task = RunDevelopment(request, kind, "", true, repair); }, true);
            AddPanelButton("Только создать ZIP", () => { var task = RunDevelopment(request, kind, "", false, repair); }, false);
            AddPanelButton("Отмена", () => OpenPanel("Разработка"), false);
            try { var data = await Relay.Targets(CancellationToken.None); if (revision != panelRevision || closed) return;
                foreach (var device in Json.Rows(data, "devices").Where(d => !Json.Flag(d, "current") && Json.Text(d, "id") != api.Account.DeviceId)) { var id = Json.Text(device, "id"); AddPanelButton("На ПК: " + Json.Text(device, "name"), () => { var task = RunDevelopment(request, kind, id, true, repair); }, false); }
            } catch { if (revision == panelRevision) panelContent.Children.Add(Label("Другие ПК недоступны. Включите приём в разделе «Разработка» на выбранном ПК.", 11, muted)); }
        }
        private async Task<string> GenerateDevelopment(string prompt, CancellationToken token) {
            var owner = api.Account.Email; var sessionId = api.SessionId; Dictionary<string, object> artifact = null;
            await api.Run(prompt, ev => { var result = Json.Map(Json.Get(ev, "result")); var file = Json.Map(Json.Get(result, "artifact")); if (Json.Text(result, "kind") == "file_pending" && Json.Text(file, "kind") == "zip") artifact = file; if (Json.Text(ev, "event") == "tool.started") SetStatus("Тройка разрабатывает проект…", false); }, AskApproval, token);
            token.ThrowIfCancellationRequested(); if (owner != api.Account.Email || sessionId != api.SessionId) throw new OperationCanceledException();
            if (artifact == null) throw new InvalidDataException("Тройка не передала ZIP проекта. Ответ без файла не считается готовым проектом.");
            var archive = await store.Receive(api, artifact, token); token.ThrowIfCancellationRequested();
            return Development.Extract(archive, Path.Combine(store.FilesFolder(owner), "projects"));
        }
        private async Task RunDevelopment(string request, string kind, string target, bool execute, bool repair) {
            if (busy || localCheck != null || developmentRelay != null && developmentRelay.Checking) return;
            busy = true; operation = new CancellationTokenSource(TimeSpan.FromMinutes(15)); localCheck = operation;
            var token = operation.Token; var workflow = Guid.NewGuid().ToString("N"); send.IsEnabled = false; microphone.Content = "Стоп";
            panelContent.Children.Clear(); panelContent.Children.Add(Label("Разрабатываю проект…", 18, text)); AddPanelButton("Остановить", () => { var task = Stop(); }, true);
            var prompt = kind == DevelopmentWorkflow.ModelReview ? DevelopmentWorkflow.ModelPrompt(request) : repair ? request : "Создай ZIP-проект по задаче: " + request + "\nВключи исходники, PLAN.md, README.md и тесты. Не объявляй локальную проверку выполненной на сервере. " + DevelopmentWorkflow.Portable(kind);
            await Safe(async () => { await DevelopmentWorkflow.Run(prompt, kind, execute, GenerateDevelopment,
                (folder, checkKind, cancellation) => target.Length == 0 ? Development.Check(folder, checkKind, cancellation) : Relay.Remote(folder, checkKind, target, workflow, cancellation),
                (folder, report) => { projectFolder = folder; checkReport = report; SetStatus(report == null ? "Версия сохранена. Проверяю…" : report.Verified ? "Проверка прошла" : "Проверка с ошибками; исправляю…", false); }, token);
                SetStatus(kind == DevelopmentWorkflow.ModelReview ? DevelopmentWorkflow.ModelReviewStatus(projectFolder) : checkReport == null ? "Проект сохранён без запуска." : checkReport.Verified ? "Проект сохранён. Проверка прошла." : "Проект сохранён. Проверка не прошла; смотрите отчёт.", checkReport != null && !checkReport.Verified);
            });
            if (api.ActiveRun.Length > 0) using (var stop = new CancellationTokenSource(12000)) { try { await api.Stop(stop.Token); } catch { SetStatus("Сервер не подтвердил остановку. Проверьте историю.", true); } }
            operation.Dispose(); operation = null; localCheck = null; busy = false; send.IsEnabled = true; Idle(); if (!closed && openPanel == "Разработка") RenderDevelopment();
        }
        private async Task ToggleDevelopmentWorker(bool enabled) {
            if (!enabled) { await Relay.Disable(); SetStatus("Приём проверок выключен.", false); return; }
            if (!api.Account.SignedIn || busy || localCheck != null) { SetStatus("Войдите и завершите текущую задачу.", true); RenderDevelopment(); return; }
            var root = Path.Combine(store.FilesFolder(api.Account.Email), "projects-from-phone");
            SetStatus("ПК готов принимать проверки с телефона.", false);
            await Relay.Enable(root, ApproveDevelopmentJob, () => !busy && localCheck == null && openPanel == "Разработка", message => { if (!closed) { SetStatus(message, false); if (openPanel == "Разработка") RenderDevelopment(); } });
            if (!closed && openPanel == "Разработка") RenderDevelopment();
        }
        private async Task<bool> ApproveDevelopmentJob(Dictionary<string, object> job, CancellationToken token) {
            if (busy || localCheck != null || openPanel != "Разработка") return false;
            developmentConsent = new TaskCompletionSource<bool>(); var pending = developmentConsent;
            panelContent.Children.Clear(); panelContent.Children.Add(Label("Проверить проект с телефона?", 18, text)); Gap();
            panelContent.Children.Add(Label(Development.Kind(Json.Text(job, "mode")) + ". Исходники сохранятся в новой папке. Код получает ваши права Windows. Разрешение действует на этот проект: до четырёх версий за 10 минут.", 12, muted)); Gap();
            AddPanelButton("Разрешить этот проект", () => pending.TrySetResult(true), true); AddPanelButton("Отклонить", () => pending.TrySetResult(false), false);
            using (token.Register(() => pending.TrySetResult(false))) { var accepted = await pending.Task; developmentConsent = null; return accepted; }
        }
    }
}
