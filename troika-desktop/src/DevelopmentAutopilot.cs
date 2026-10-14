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
        public DevelopmentAutopilot(ApiClient api, LocalStore store) { this.api = api; this.store = store; }
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
                foreach (var project in Projects) {
                    var id = Json.Text(project, "run_id");
                    var artifact = Json.Map(Json.Get(project, "artifact"));
                    if (Json.Text(project, "status") == "completed" && artifact.Count > 0 && !Results.ContainsKey(id)) {
                        try {
                            var archive = await store.Receive(api, artifact, token);
                            if (identity != api.Account.Email) return;
                            Results[id] = Json.Text(artifact, "kind") == "zip" ? Development.Extract(archive, Path.Combine(store.FilesFolder(owner), "projects")) : archive;
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
            await api.Call("POST", "/v1/runs", new { workflow = "development", input = task, title = task.Substring(0, Math.Min(task.Length, 70)), free_only = true, artifact_delivery = "device", idempotency_key = key, files = sources == null ? null : sources.Select(p => new { path = p.Key, content = p.Value }).ToArray() }, token);
            if (identity != api.Account.Email) throw new OperationCanceledException();
            startKeys.Remove(fingerprint);
            await Refresh(token);
        }
        public Task Stop(string id, CancellationToken token) { return api.Call("POST", "/v1/runs/" + Uri.EscapeDataString(id) + "/stop", new { }, token); }
        public ProjectReport NextReport(bool idle) { return idle && VoiceReports && owner == api.Account.Email && reports.Count > 0 ? reports.Peek() : null; }
        public void ReportSpoken(ProjectReport report) { if (owner != api.Account.Email || !Projects.Any(p => Json.Text(p, "run_id") == report.RunId)) return; seen.Add(report.Key); if (reports.Count > 0 && reports.Peek().Key == report.Key) reports.Dequeue(); Remember(); }
        public static bool Terminal(string status) { return status == "completed" || status == "failed" || status == "cancelled"; }
        public static string Stage(string value) {
            switch (value) {
                case "queued": return "В очереди"; case "planning": return "План"; case "designing": return "Дизайн";
                case "implementing": return "Создание проекта"; case "reviewing": return "Проверка исходников";
                case "repairing": return "Исправление"; case "completed": return "Результат готов";
                case "waiting_limit": return "Жду лимит бесплатной модели";
                case "cancelled": return "Остановлено"; case "failed": return "Требуется внимание"; default: return "Выполняется";
            }
        }
    }
}
