using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    // Temporary account-bound transport. Project code only runs on the consenting PC.
    public sealed class DevelopmentRelay {
        private readonly ApiClient api;
        private readonly Dictionary<string, Tuple<DateTime, int>> consents = new Dictionary<string, Tuple<DateTime, int>>();
        private CancellationTokenSource worker;
        private string owner = "", session = "";
        public bool Enabled { get { return worker != null; } }
        public bool Checking { get; private set; }
        public DevelopmentRelay(ApiClient api) { this.api = api; }
        public Task<Dictionary<string, object>> Targets(CancellationToken token) { return api.Get("/v1/development/devices", token); }
        public async Task<CheckReport> Remote(string folder, string kind, string target, string workflow, CancellationToken token) {
            var email = api.Account.Email; var sessionId = api.SessionId;
            var job = await api.Call("POST", "/v1/development/checks", new { files = Development.Sources(folder), mode = Development.Mode(kind), target_device_id = target, workflow_id = workflow }, token);
            var path = "/v1/development/checks/" + Uri.EscapeDataString(Json.Text(job, "id"));
            CheckReport outcome = null; Exception failure = null;
            try { outcome = await WaitRemote(path, kind, email, sessionId, token); } catch (Exception error) { failure = error; }
            if (email == api.Account.Email && sessionId == api.SessionId) using (var stop = new CancellationTokenSource(10000)) { try { await api.Call("DELETE", path, null, stop.Token); } catch { } }
            if (failure != null) throw failure; return outcome;
        }
        private async Task<CheckReport> WaitRemote(string path, string kind, string email, string sessionId, CancellationToken token) {
                var deadline = DateTime.UtcNow.AddMinutes(3);
                while (DateTime.UtcNow < deadline) {
                    token.ThrowIfCancellationRequested(); if (email != api.Account.Email || sessionId != api.SessionId) throw new OperationCanceledException();
                    var current = await api.Get(path, token); var state = Json.Text(current, "state");
                    if (state == "cancelled") return new CheckReport { Kind = kind, Stopped = true, Output = "Проверка отменена на выбранном ПК." };
                    if (state == "completed") {
                        var value = Json.Map(Json.Get(current, "report")); var result = new CheckReport { Kind = kind, ExitCode = (int)Json.Number(value, "exit_code"), Output = Json.Text(value, "output"), Stopped = Json.Flag(value, "cancelled"), TimedOut = Json.Flag(value, "timed_out"), NoTests = Json.Flag(value, "no_tests") };
                        result.Verified = result.ExitCode == 0 && !result.Stopped && !result.TimedOut && !result.NoTests; return result;
                    }
                    await Task.Delay(1000, token);
                }
                return new CheckReport { Kind = kind, TimedOut = true, Output = "ПК не завершил проверку вовремя." };
        }
        public async Task Enable(string root, Func<Dictionary<string, object>, CancellationToken, Task<bool>> approve, Func<bool> ready, Action<string> status) {
            if (Enabled) return;
            owner = api.Account.Email; session = api.SessionId; worker = new CancellationTokenSource();
            var active = worker;
            try {
                while (!active.IsCancellationRequested && owner == api.Account.Email && session == api.SessionId) {
                    var data = await api.Call("POST", "/v1/development/worker", new { enabled = true, claim = ready() }, active.Token);
                    var job = Json.Map(Json.Get(data, "job"));
                    if (job.Count > 0) await Execute(root, job, approve, status, active.Token);
                    await Task.Delay(5000, active.Token);
                }
            } catch (OperationCanceledException) { }
            catch (Exception error) { status("Приём проверок остановлен: " + error.Message); }
            finally { if (worker == active) { worker = null; consents.Clear(); } active.Dispose(); }
        }
        public async Task Disable() {
            var active = worker; if (active != null) active.Cancel(); consents.Clear();
            if (owner == api.Account.Email && session == api.SessionId && api.Account.SignedIn) using (var stop = new CancellationTokenSource(10000)) { try { await api.Call("POST", "/v1/development/worker", new { enabled = false }, stop.Token); } catch { } }
        }
        private async Task Execute(string root, Dictionary<string, object> job, Func<Dictionary<string, object>, CancellationToken, Task<bool>> approve, Action<string> status, CancellationToken token) {
            Checking = true;
            var path = "/v1/development/checks/" + Uri.EscapeDataString(Json.Text(job, "id"));
            using (var run = CancellationTokenSource.CreateLinkedTokenSource(token)) {
                var heartbeat = Heartbeat(path, run);
                try {
                    var key = Json.Text(job, "requester_device_id") + ":" + Json.Text(job, "workflow_id"); Tuple<DateTime, int> consent;
                    bool allowed = consents.TryGetValue(key, out consent) && DateTime.UtcNow - consent.Item1 < TimeSpan.FromMinutes(10) && consent.Item2 < 4;
                    if (!allowed) { allowed = await approve(job, run.Token); consent = Tuple.Create(DateTime.UtcNow, 0); }
                    run.Token.ThrowIfCancellationRequested();
                    if (!allowed) { await api.Call("DELETE", path, null, run.Token); return; }
                    consents[key] = Tuple.Create(consent.Item1, consent.Item2 + 1);
                    var sources = Json.Map(Json.Get(job, "files")); int bytes = 0;
                    var archive = Path.Combine(root, "incoming-" + Guid.NewGuid().ToString("N") + ".zip"); Directory.CreateDirectory(root);
                    string folder;
                    try {
                        using (var zip = ZipFile.Open(archive, ZipArchiveMode.Create)) foreach (var item in sources) {
                            if (!(item.Value is string) || sources.Count > 100 || (bytes += Encoding.UTF8.GetByteCount((string)item.Value)) > 120000) throw new InvalidDataException("Недопустимый размер проекта.");
                            Development.ValidateSource(item.Key, (string)item.Value);
                            using (var writer = new StreamWriter(zip.CreateEntry(item.Key).Open(), new UTF8Encoding(false))) writer.Write((string)item.Value);
                        }
                        folder = Development.Extract(archive, root);
                    } finally { if (File.Exists(archive)) File.Delete(archive); }
                    run.Token.ThrowIfCancellationRequested();
                    if (Json.Text(await api.Get(path, run.Token), "state") != "running") return;
                    status("Проверяю проект с телефона…");
                    var result = await Development.Check(folder, Development.Kind(Json.Text(job, "mode")), run.Token);
                    run.Token.ThrowIfCancellationRequested();
                    await api.Call("POST", path + "/report", new { lease = Json.Text(job, "lease"), report = new { exit_code = result.ExitCode, output = BoundedOutput(result.Output), cancelled = result.Stopped && !result.TimedOut, timed_out = result.TimedOut, no_tests = result.NoTests } }, run.Token);
                    status(result.Verified ? "Отчёт отправлен: проверка прошла." : "Отчёт с ошибками отправлен на телефон.");
                } catch (OperationCanceledException) { status("Проверка с телефона остановлена."); }
                finally { run.Cancel(); Checking = false; status("ПК готов принимать проверки с телефона."); }
            }
        }
        private async Task Heartbeat(string path, CancellationTokenSource run) {
            var token = run.Token;
            try { while (!token.IsCancellationRequested) { await Task.Delay(4000, token); await api.Call("POST", "/v1/development/worker", new { enabled = true, claim = false }, token); if (Json.Text(await api.Get(path, token), "state") != "running" || owner != api.Account.Email || session != api.SessionId) run.Cancel(); } }
            catch { if (!token.IsCancellationRequested) try { run.Cancel(); } catch (ObjectDisposedException) { } }
        }
        private static string BoundedOutput(string output) {
            var data = Encoding.UTF8.GetBytes(output); if (data.Length <= 64000) return output;
            var strict = new UTF8Encoding(false, true); for (int size = 64000; size > 63996; size--) { try { return strict.GetString(data, 0, size); } catch (DecoderFallbackException) { } } return "Вывод превышает допустимый размер.";
        }
    }
}
