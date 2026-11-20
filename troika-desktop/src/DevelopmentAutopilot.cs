using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed class ProjectReport {
        public string Key, Text, RunId;
    }
    public sealed class DevelopmentAutopilot {
        private readonly ApiClient api;
        private readonly LocalStore store;
        private readonly DevelopmentCheckpoints checkpoints;
        private readonly Dictionary<string, DateTime> resumeAfter = new Dictionary<string, DateTime>();
        private string owner = "";
        private bool refreshing;
        private readonly HashSet<string> seen = new HashSet<string>();
        private readonly Queue<ProjectReport> reports = new Queue<ProjectReport>();
        private readonly Dictionary<string, string> startKeys = new Dictionary<string, string>();
        public List<Dictionary<string, object>> Projects = new List<Dictionary<string, object>>();
        public readonly Dictionary<string, string> Results = new Dictionary<string, string>();
        public bool IsPro, VoiceReports = true;
        public string Error = "";
        public Action OnAccountChanged;
        public DevelopmentAutopilot(ApiClient api, LocalStore store) { this.api = api; this.store = store; checkpoints = new DevelopmentCheckpoints(store); }
        private string StateFile { get { return Path.Combine(store.FilesFolder(owner), ".project-reports.json"); } }
        private void Remember() {
            if (owner.Length > 0) LocalStore.WriteAtomic(StateFile, System.Text.Encoding.UTF8.GetBytes(Json.Encode(new { voice = VoiceReports, seen = seen.Take(400).ToArray() })));
        }
        public void SetVoice(bool enabled) {
            VoiceReports = enabled;
            if (!enabled) { foreach (var report in reports) seen.Add(report.Key); reports.Clear(); }
            Remember();
        }
        public async Task Refresh(CancellationToken token) {
            if (refreshing) return;
            if (owner != api.Account.Email) {
                if (OnAccountChanged != null) OnAccountChanged();
                owner = api.Account.Email; Projects.Clear(); Results.Clear(); reports.Clear(); seen.Clear(); startKeys.Clear(); IsPro = false; VoiceReports = true;
                try { var saved = Json.Parse(File.ReadAllText(StateFile)); VoiceReports = Json.Get(saved, "voice") == null || Json.Flag(saved, "voice"); var ids = Json.Get(saved, "seen") as System.Collections.IEnumerable; if (ids != null) foreach (var id in ids) seen.Add(Convert.ToString(id)); } catch { }
            }
            if (!api.Account.SignedIn) return;
            var identity = owner; refreshing = true;
            try {
                var snapshot = await api.Get("/v1/development/projects", token);
                if (identity != api.Account.Email) return;
                IsPro = Json.Flag(snapshot, "enabled"); Projects = Json.Rows(snapshot, "projects").ToList(); Error = "";
                var visibleRuns = new HashSet<string>(Projects.Select(p => Json.Text(p,"run_id")));
                foreach (var retired in reports.Where(r => !visibleRuns.Contains(r.RunId))) seen.Add(retired.Key);
                var currentReports = reports.Where(r => visibleRuns.Contains(r.RunId)).ToList();
                reports.Clear(); foreach (var currentReport in currentReports) reports.Enqueue(currentReport);
                foreach (var project in Projects) {
                    var id = Json.Text(project, "run_id");
                    var projectId = Json.Text(project, "project_id");
                    if (projectId.Length > 0 && Json.Number(project, "checkpoint_revision") > 0) {
                        try {
                            var local = checkpoints.Read(identity, projectId);
                            if (local == null || Json.Number(local, "revision") < Json.Number(project, "checkpoint_revision")) {
                                try {
                                    var value = await api.Get("/v1/development/projects/" + projectId + "/checkpoint", token);
                                    if (identity != api.Account.Email) return;
                                    if (local != null) foreach (var field in new[] { "pending_instruction", "pending_budget" }) if (local.ContainsKey(field)) value[field] = local[field];
                                    value["title"] = Json.Text(project, "title").Length > 0 ? Json.Text(project, "title") : Json.Text(local ?? new Dictionary<string, object>(), "title");
                                    checkpoints.Save(identity, projectId, value); local = checkpoints.Read(identity, projectId);
                                    await api.Call("POST", "/v1/development/projects/" + projectId + "/checkpoint/received", new { revision = (int)Json.Number(value, "revision"), digest = Json.Text(value, "digest") }, token);
                                } catch { project["checkpoint_error"] = "Последняя копия ещё не сохранена на ПК."; }
                            }
                            project["local_checkpoint"] = local != null;
                            if (local != null && Json.Number(local,"revision") == Json.Number(project,"checkpoint_revision") && Json.Number(project,"checkpoint_confirmed") < Json.Number(local,"revision"))
                                await api.Call("POST","/v1/development/projects/"+projectId+"/checkpoint/received",new {revision=(int)Json.Number(local,"revision"),digest=Json.Text(local,"digest")},token);
                            if (Json.Text(project, "title").Length == 0 && local != null) project["title"] = Json.Text(local, "title");
                            var pending = local != null && local.ContainsKey("pending_instruction") && Json.Text(project, "status") == "paused";
                            DateTime next;
                            if (local != null && (pending || Json.Text(project, "status") == "interrupted") && (!resumeAfter.TryGetValue(projectId, out next) || DateTime.UtcNow >= next)) {
                                resumeAfter[projectId] = DateTime.UtcNow.AddSeconds(30);
                                await Resume(project, pending ? Json.Text(local, "pending_instruction") : "", pending ? (int)Json.Number(local, "pending_budget") : 100000, token, !pending);
                            }
                        } catch { project["checkpoint_error"] = "Для продолжения подтвердите бюджет локальной контрольной копии."; }
                    }
                    var artifact = Json.Map(Json.Get(project, "artifact"));
                    if (Json.Text(project, "status") == "completed" && artifact.Count > 0 && !Results.ContainsKey(id)) {
                        try {
                            var archive = await store.Receive(api, artifact, token);
                            if (identity != api.Account.Email) return;
                            Results[id] = Json.Text(artifact, "kind") == "zip" ? Development.Extract(archive, Path.Combine(store.FilesFolder(owner), "projects")) : archive;
                        } catch (InvalidDataException error) {
                            project["delivery_error"] = "Не удалось открыть результат: " + error.Message;
                        } catch { project["delivery_error"] = "Результат ещё не сохранён. Проверьте сеть и повторите скачивание."; }
                    }
                    var available = Json.Rows(project, "reports").ToList();
                    if (Terminal(Json.Text(project, "status")) && available.Count > 0) {
                        var latestKey = id + ":" + Json.Text(available.Last(), "id");
                        var kept = reports.Where(r => r.RunId != id || r.Key == latestKey).ToList(); foreach (var r in reports.Where(r => r.RunId == id && r.Key != latestKey)) seen.Add(r.Key); reports.Clear(); foreach (var r in kept) reports.Enqueue(r);
                        available = available.Skip(available.Count - 1).ToList();
                    }
                    foreach (var report in available) {
                        var key = id + ":" + Json.Text(report, "id"); var message = Json.Text(report, "text");
                        if (!VoiceReports) { seen.Add(key); continue; }
                        if (!seen.Contains(key) && !reports.Any(r => r.Key == key) && message.Length > 0) reports.Enqueue(new ProjectReport { Key = key, Text = Json.Text(project, "title") + ". " + message, RunId = id });
                    }
                }
            } catch (Exception exception) { if (identity == api.Account.Email) Error = exception is ApiException && ((ApiException)exception).Status == 404 ? "Для автопилота требуется обновить сервер Тройки." : exception.Message; }
            finally { refreshing = false; }
        }
        public async Task Start(string task, Dictionary<string, string> sources, CancellationToken token) {
            await Refresh(token);
            var handshake = await api.Get("/v1/development/projects", token);
            if (!Json.Flag(handshake, "enabled")) throw new InvalidOperationException("Разработка доступна только в Pro.");
            var identity = api.Account.Email;
            string fingerprint; using (var hash = System.Security.Cryptography.SHA256.Create()) fingerprint = Convert.ToBase64String(hash.ComputeHash(System.Text.Encoding.UTF8.GetBytes(Json.Encode(new { identity, task, sources }))));
            string key; if (!startKeys.TryGetValue(fingerprint, out key)) startKeys[fingerprint] = key = "development-" + Guid.NewGuid().ToString("N");
            await api.Call("POST", "/v1/runs", new { workflow = "development", input = task, title = task.Substring(0, Math.Min(task.Length, 70)), free_only = true, budget_tokens=250000, budget_approved=true, artifact_delivery = "device", idempotency_key = key, files = sources == null ? null : sources.Select(p => new { path = p.Key, content = p.Value }).ToArray() }, token);
            if (identity != api.Account.Email) throw new OperationCanceledException();
            startKeys.Remove(fingerprint);
            await Refresh(token);
        }
        public Task Stop(string id, CancellationToken token) {
            var project = Projects.FirstOrDefault(p => Json.Text(p, "run_id") == id);
            if (project != null && Json.Text(project, "project_id").Length > 0)
                return api.Call("POST", "/v1/development/projects/" + Json.Text(project, "project_id") + "/control", new { action = "stop" }, token);
            return api.Call("POST", "/v1/runs/" + Uri.EscapeDataString(id) + "/stop", new { }, token);
        }
        public Task Pause(Dictionary<string, object> project, CancellationToken token) {
            return api.Call("POST", "/v1/development/projects/" + Json.Text(project, "project_id") + "/control", new { action = "pause" }, token);
        }
        public async Task Clarify(Dictionary<string, object> project, string instruction, int budget, CancellationToken token) {
            var identity = api.Account.Email; var id = Json.Text(project, "project_id"); var local = checkpoints.Read(identity, id);
            if (local == null) throw new InvalidOperationException("Дождитесь первой локальной контрольной копии.");
            local["pending_instruction"] = instruction; local["pending_budget"] = budget; checkpoints.Save(identity, id, local);
            await Pause(project, token);
        }
        public async Task Resume(Dictionary<string, object> project, string instruction, int budget, CancellationToken token, bool reuseBudget = false) {
            var identity = api.Account.Email; var id = Json.Text(project, "project_id"); var local = checkpoints.Read(identity, id);
            if (local == null) throw new InvalidOperationException("На ПК нет контрольной копии проекта.");
            var fingerprint = LocalStore.Hash(System.Text.Encoding.UTF8.GetBytes(Json.Encode(new { id, revision = Json.Number(local, "revision"), instruction, budget, reuseBudget })));
            string key; if (!startKeys.TryGetValue(fingerprint, out key)) startKeys[fingerprint] = key = "resume-" + Guid.NewGuid().ToString("N");
            await api.Call("POST", "/v1/development/projects/" + id + "/resume", new { checkpoint = Json.Get(local, "checkpoint"), revision = (int)Json.Number(local, "revision"), title = Json.Text(local, "title"), instruction, budget_tokens = budget, reuse_budget = reuseBudget, idempotency_key = key }, token);
            startKeys.Remove(fingerprint);
            if (identity != api.Account.Email) return;
            local = checkpoints.Read(identity, id);
            if (local != null && Json.Text(local, "pending_instruction") == instruction) { local.Remove("pending_instruction"); local.Remove("pending_budget"); checkpoints.Save(identity, id, local); }
        }
        public ProjectReport NextReport(bool idle) { return idle && VoiceReports && owner == api.Account.Email && reports.Count > 0 ? reports.Peek() : null; }
        public void ReportSpoken(ProjectReport report) { if (owner != api.Account.Email || !Projects.Any(p => Json.Text(p, "run_id") == report.RunId)) return; seen.Add(report.Key); if (reports.Count > 0 && reports.Peek().Key == report.Key) reports.Dequeue(); Remember(); }
        public static bool Terminal(string status) { return status == "completed" || status == "failed" || status == "cancelled" || status == "paused" || status == "waiting_budget" || status == "interrupted"; }
        public static string Stage(string value) {
            switch (value) {
                case "queued": return "В очереди"; case "planning": return "План"; case "designing": return "Дизайн";
                case "implementing": return "Создание проекта"; case "reviewing": return "Проверка исходников";
                case "testing": return "Запускаю тесты в изолированной среде"; case "visual_review": return "Проверяю готовый дизайн";
                case "repairing": return "Исправление"; case "completed": return "Результат готов";
                case "waiting_limit": return "Жду лимит бесплатной модели";
                case "cancelled": return "Остановлено"; case "failed": return "Требуется внимание"; default: return "Выполняется";
                case "paused": return "На паузе"; case "pausing": return "Сохраняю и ставлю на паузу";
                case "waiting_budget": return "Нужно подтвердить продолжение"; case "interrupted": return "Восстанавливаю из локальной копии";
            }
        }
    }
}
