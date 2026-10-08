using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Authentication;

namespace Troika.Desktop {
    sealed class FakeHandler : HttpMessageHandler {
        public Func<HttpRequestMessage, Task<HttpResponseMessage>> Route;
        public readonly List<string> Requests = new List<string>();
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) { Requests.Add(request.Method + " " + request.RequestUri.AbsolutePath); return Route(request); }
        public static HttpResponseMessage Reply(string text, int status) { return new HttpResponseMessage((HttpStatusCode)status) { Content = new StringContent(text, Encoding.UTF8, "application/json") }; }
        public static Task<HttpResponseMessage> Value(string text, int status) { return Task.FromResult(Reply(text, status)); }
    }
    static class DesktopTests {
        static int passed;
        static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
        static async Task Test(string name, Func<Task> work) { await work(); passed++; Console.WriteLine("PASS " + name); }
        static AccountSession Session() { return new AccountSession { Email = "test@example.com", Token = "trk_live_test", RefreshToken = "trk_refresh_test", HomeSession = "home_test", ExpiresAt = 9999999999 }; }
        static ApiClient Client(FakeHandler handler) { return new ApiClient(handler, "https://example.test") { Account = Session(), SessionId = "home_test" }; }
        static FakeHandler RunHandler(string events, string state) {
            var handler = new FakeHandler(); handler.Route = async request => {
                var path = request.RequestUri.AbsolutePath;
                if (path == "/v1/capabilities") return FakeHandler.Reply("{\"features\":{\"device_file_delivery\":true}}", 200);
                if (path == "/v1/runs") { var body = Json.Parse(await request.Content.ReadAsStringAsync()); Assert(Json.Text(body, "artifact_delivery") == "device", "local delivery missing"); Assert(Json.Text(body, "session_id") == "home_test", "session missing"); return FakeHandler.Reply("{\"run_id\":\"run_test\"}", 202); }
                if (path.EndsWith("/events")) return FakeHandler.Reply(events, 200);
                if (path.EndsWith("/approval")) return FakeHandler.Reply("{\"ok\":true}", 200);
                if (path == "/v1/runs/run_test") return FakeHandler.Reply(state, 200);
                throw new Exception("Unexpected route " + path);
            }; return handler;
        }
        static async Task ExpectError(Func<Task> work, string fragment) { try { await work(); } catch (Exception error) { Assert(error.Message.Contains(fragment), "wrong error: " + error.Message); return; } throw new Exception("Expected failure: " + fragment); }
        static string Event(object value) { return "data: " + Json.Encode(value) + "\n\n"; }
        static string Temporary() { var path = Path.Combine(Path.GetTempPath(), "troika-desktop-test-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(path); return path; }
        static string Zip(string root, string name, string content) { var path = Path.Combine(root, Guid.NewGuid().ToString("N") + ".zip"); using (var zip = ZipFile.Open(path, ZipArchiveMode.Create)) { var entry = zip.CreateEntry(name); using (var writer = new StreamWriter(entry.Open(), Encoding.UTF8)) writer.Write(content); } return path; }
        static Dictionary<string, object> Delivery(byte[] bytes) { return Json.Parse(Json.Encode(new { id = "delivery_12345678901234567890123456789012", filename = "test.pdf", size = bytes.Length, sha256 = LocalStore.Hash(bytes) })); }
        static async Task RunAll() {
            await Test("streamed answer excludes private reasoning", async () => {
                var events = Event(new { @event = "reasoning.available", text = "private" }) + Event(new { @event = "message.delta", delta = "Готово" }) + Event(new { @event = "run.completed" });
                using (var api = Client(RunHandler(events, "{}"))) { var visible = new List<string>(); var answer = await api.Run("test", ev => visible.Add(Json.Text(ev, "event")), null, CancellationToken.None); Assert(answer == "Готово" && !visible.Contains("reasoning.available"), "reasoning leak"); }
            });
            await Test("partial text is not success on run failure", async () => {
                var events = Event(new { @event = "message.delta", delta = "partial" }) + Event(new { @event = "run.failed" }); using (var api = Client(RunHandler(events, "{}"))) await ExpectError(async () => { await api.Run("test", null, null, CancellationToken.None); }, "не смогла завершить");
            });
            await Test("disconnect does not mark running task complete", async () => {
                using (var api = Client(RunHandler(Event(new { @event = "message.delta", delta = "partial" }), "{\"status\":\"running\"}"))) await ExpectError(async () => { await api.Run("test", null, null, CancellationToken.None); }, "прервалось");
            });
            await Test("completed status recovers missing SSE answer", async () => { using (var api = Client(RunHandler("", "{\"status\":\"completed\",\"output\":\"recovered\"}"))) Assert(await api.Run("test", null, null, CancellationToken.None) == "recovered", "missing recovered result"); });
            await Test("unsupported local delivery blocks run creation", async () => {
                var handler = new FakeHandler { Route = request => FakeHandler.Value("{\"features\":{}}", 200) }; using (var api = Client(handler)) { await ExpectError(async () => { await api.Run("test", null, null, CancellationToken.None); }, "Обновите сервер"); Assert(handler.Requests.Count == 1, "run started without capability"); }
            });
            await Test("unadvertised approval choice fails closed", async () => {
                var events = Event(new { @event = "approval.request", choices = new[] { "once", "deny" } }) + Event(new { @event = "message.delta", delta = "ok" }) + Event(new { @event = "run.completed" }); var handler = RunHandler(events, "{}"); var route = handler.Route;
                handler.Route = async request => { if (request.RequestUri.AbsolutePath.EndsWith("/approval")) Assert(Json.Text(Json.Parse(await request.Content.ReadAsStringAsync()), "choice") == "deny", "unsafe approval"); return await route(request); };
                using (var api = Client(handler)) await api.Run("test", null, ev => Task.FromResult("always"), CancellationToken.None);
            });
            await Test("daily quota has an actionable error", async () => {
                var handler = new FakeHandler { Route = request => FakeHandler.Value("{\"error\":{\"code\":\"daily_request_limit_exceeded\"}}", 429) }; using (var api = Client(handler)) await ExpectError(async () => { await api.Get("/v1/subscription", CancellationToken.None); }, "Дневной лимит");
            });
            await Test("parallel requests refresh only once", async () => {
                int refreshes = 0; var handler = new FakeHandler { Route = async request => { if (request.RequestUri.AbsolutePath.EndsWith("/refresh")) { refreshes++; await Task.Delay(20); return FakeHandler.Reply("{\"access_token\":\"trk_live_new\",\"refresh_token\":\"trk_refresh_new\",\"home_session_id\":\"home_test\",\"access_expires_at\":9999999999}", 200); } Assert(request.Headers.Authorization.Parameter == "trk_live_new", "stale token"); return FakeHandler.Reply("{}", 200); } };
                using (var api = Client(handler)) { api.Account.ExpiresAt = 0; await Task.WhenAll(api.Get("/a", CancellationToken.None), api.Get("/b", CancellationToken.None)); Assert(refreshes == 1, "duplicate refresh"); }
            });
            await Test("401 refreshes and retries the authenticated request", async () => {
                int calls = 0; var handler = new FakeHandler { Route = request => { if (request.RequestUri.AbsolutePath.EndsWith("/refresh")) return FakeHandler.Value("{\"access_token\":\"trk_live_new\",\"refresh_token\":\"trk_refresh_new\",\"home_session_id\":\"home_test\",\"access_expires_at\":9999999999}", 200); calls++; return FakeHandler.Value("{}", calls == 1 ? 401 : 200); } }; using (var api = Client(handler)) await api.Get("/a", CancellationToken.None); Assert(calls == 2, "missing retry");
            });
            await Test("TLS handshake failure retries before sending request", async () => {
                int calls = 0; var handler = new FakeHandler { Route = request => { if (++calls == 1) throw new HttpRequestException("TLS", new AuthenticationException("handshake")); return FakeHandler.Value("{}", 200); } }; using (var api = Client(handler)) await api.Get("/a", CancellationToken.None); Assert(calls == 2, "TLS recovery missing");
            });
            await Test("ambiguous transport failure never repeats an action", async () => {
                int calls = 0; var handler = new FakeHandler { Route = request => { calls++; throw new HttpRequestException("transport", new IOException("after request sent")); } }; using (var api = Client(handler)) await ExpectError(async () => { await api.Call("POST", "/a", new { title = "action" }, CancellationToken.None); }, "transport"); Assert(calls == 1, "ambiguous action repeated");
            });
            await Test("credentials never leave configured origin", async () => {
                var handler = new FakeHandler { Route = request => FakeHandler.Value("{}", 200) }; using (var api = Client(handler)) await ExpectError(async () => { await api.Download("https://other.test/file", 1024, CancellationToken.None); }, "другой сервер"); Assert(handler.Requests.Count == 0, "credentials sent externally");
            });
            await Test("download size is bounded", async () => {
                var handler = new FakeHandler { Route = request => FakeHandler.Value(new string('x', 200), 200) }; using (var api = Client(handler)) await ExpectError(async () => { await api.Download("/file", 100, CancellationToken.None); }, "размер");
            });
            await Test("DPAPI protects account and files remain owner scoped", () => {
                var path = Temporary(); try { var store = new LocalStore(path); var session = Session(); store.SaveSession(session); Assert(store.LoadSession().Token == session.Token, "session roundtrip"); Assert(!Encoding.UTF8.GetString(File.ReadAllBytes(Path.Combine(path, "session.dat"))).Contains(session.Token), "plaintext token"); Assert(store.FilesFolder("a@example.com") != store.FilesFolder("b@example.com"), "owner folders shared"); store.ForgetSession(); Assert(!store.LoadSession().SignedIn, "logout retained credential"); } finally { Directory.Delete(path, true); } return Task.FromResult(0);
            });
            await Test("corrupt file never gets acknowledged", async () => {
                var path = Temporary(); try { var bytes = Encoding.ASCII.GetBytes("%PDF-test"); var delivery = Delivery(bytes); var handler = new FakeHandler { Route = request => FakeHandler.Value("corrupt", 200) }; using (var api = Client(handler)) await ExpectError(async () => { await new LocalStore(path).Receive(api, delivery, CancellationToken.None); }, "повреждён"); Assert(!handler.Requests.Any(r => r.EndsWith("/received")), "corrupt ACK"); } finally { Directory.Delete(path, true); }
            });
            await Test("save precedes ACK and lost ACK retries without duplicate", async () => {
                var path = Temporary(); try { var bytes = Encoding.ASCII.GetBytes("%PDF-test"); var delivery = Delivery(bytes); var store = new LocalStore(path); int downloads = 0, acknowledgements = 0;
                    var handler = new FakeHandler { Route = request => { if (request.Method == HttpMethod.Get) { downloads++; var reply = new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) }; return Task.FromResult(reply); } acknowledgements++; Assert(store.Files(Session().Email).Count() == 1, "ACK before save"); return FakeHandler.Value("{}", acknowledgements == 1 ? 503 : 200); } };
                    using (var api = Client(handler)) { await ExpectError(async () => { await store.Receive(api, delivery, CancellationToken.None); }, "503"); var saved = await store.Receive(api, delivery, CancellationToken.None); Assert(File.ReadAllBytes(saved).SequenceEqual(bytes), "invalid saved bytes"); } Assert(downloads == 1 && acknowledgements == 2 && store.Files(Session().Email).Count() == 1, "duplicate delivery");
                } finally { Directory.Delete(path, true); }
            });
            await Test("unsafe filenames fail before download", async () => {
                var path = Temporary(); try { var delivery = Delivery(new byte[] { 1 }); var handler = new FakeHandler { Route = request => FakeHandler.Value("{}", 200) }; using (var api = Client(handler)) foreach (var name in new[] { "../outside.pdf", "C:\\outside.pdf", "CON.pdf", "a:stream", "a.pdf." }) { delivery["filename"] = name; await ExpectError(async () => { await new LocalStore(path).Receive(api, delivery, CancellationToken.None); }, "имя файла"); } Assert(handler.Requests.Count == 0, "unsafe name reached API"); } finally { Directory.Delete(path, true); }
            });
            await Test("PCM becomes valid 16 kHz mono WAV", () => { var audio = VoiceRecorder.Wav(new byte[32000]); Assert(audio.Length == 32044 && Encoding.ASCII.GetString(audio, 0, 4) == "RIFF" && BitConverter.ToInt32(audio, 24) == 16000 && BitConverter.ToInt16(audio, 22) == 1 && BitConverter.ToInt32(audio, 40) == 32000, "invalid WAV"); return Task.FromResult(0); });
            await Test("stop targets only the active run", async () => {
                var handler = new FakeHandler { Route = request => FakeHandler.Value("{}", 200) }; using (var api = Client(handler)) { api.ActiveRun = "run_test"; await api.Stop(CancellationToken.None); Assert(api.ActiveRun == "" && handler.Requests.Single() == "POST /v1/runs/run_test/stop", "wrong stop scope"); }
            });
            await Test("ZIP traversal and hidden secrets are rejected", () => {
                var root = Temporary(); try { foreach (var name in new[] { "../outside.py", ".env", "nested/../../outside.py", "nested/.git/config.txt", "run.exe" }) { bool blocked = false; try { Development.Extract(Zip(root, name, "test"), Path.Combine(root, "projects")); } catch (InvalidDataException) { blocked = true; } Assert(blocked, "unsafe ZIP accepted"); } Assert(!File.Exists(Path.Combine(root, "outside.py")), "ZIP escaped folder"); } finally { Directory.Delete(root, true); } return Task.FromResult(0);
            });
            await Test("each project extraction preserves the original", () => {
                var root = Temporary(); try { var archive = Zip(root, "main.py", "print('ok')"); var original = File.ReadAllBytes(archive); var first = Development.Extract(archive, Path.Combine(root, "projects")); var second = Development.Extract(archive, Path.Combine(root, "projects")); Assert(first != second && File.Exists(Path.Combine(first, "main.py")) && File.ReadAllBytes(archive).SequenceEqual(original), "project overwrite"); } finally { Directory.Delete(root, true); } return Task.FromResult(0);
            });
            await Test("real Python failure, repair, and test pass", async () => {
                var root = Temporary(); try { File.WriteAllText(Path.Combine(root, "test_calc.py"), "import unittest\nclass Calculation(unittest.TestCase):\n def test_sum(self):\n  self.assertEqual(2 + 2, 5)\n"); var failure = await Development.Check(root, "Python: тесты", CancellationToken.None); Assert(!failure.Verified && failure.ExitCode != 0 && failure.Output.Contains("FAIL"), "failed test marked verified"); File.WriteAllText(Path.Combine(root, "test_calc.py"), "import unittest\nclass Calculation(unittest.TestCase):\n def test_sum(self):\n  self.assertEqual(2 + 2, 4)\n"); var fixedReport = await Development.Check(root, "Python: тесты", CancellationToken.None); Assert(fixedReport.Verified && fixedReport.ExitCode == 0, "repaired test did not pass"); } finally { Directory.Delete(root, true); }
            });
            await Test("zero tests never verify a project", async () => {
                var root = Temporary(); try { File.WriteAllText(Path.Combine(root, "main.py"), "print('ok')"); var report = await Development.Check(root, "Python: тесты", CancellationToken.None); Assert(report.ExitCode == 0 && !report.Verified, "zero tests marked verified"); var syntax = await Development.Check(root, "Python: синтаксис", CancellationToken.None); Assert(syntax.Verified && syntax.Output.Contains("поведение не проверялись"), "syntax claimed runtime verification"); } finally { Directory.Delete(root, true); }
            });
            await Test("local Stop terminates the running check", async () => {
                var root = Temporary(); try { File.WriteAllText(Path.Combine(root, "test_wait.py"), "import unittest, time\nclass Waiting(unittest.TestCase):\n def test_wait(self):\n  time.sleep(30)\n"); using (var stop = new CancellationTokenSource(700)) { var started = DateTime.UtcNow; var report = await Development.Check(root, "Python: тесты", stop.Token); Assert(report.Stopped && !report.Verified && (DateTime.UtcNow - started).TotalSeconds < 8, "Stop failed"); } } finally { Directory.Delete(root, true); }
            });
            await Test("repair context blocks secrets and redacts reports", () => {
                var root = Temporary(); try { var report = new CheckReport { Output = "token=trk_live_secret" }; File.WriteAllText(Path.Combine(root, "main.py"), "print('ok')"); Assert(!Development.RepairContext(root, report).Contains("trk_live_secret"), "report secret sent"); File.WriteAllText(Path.Combine(root, "main.py"), "api_key = 'private'"); bool blocked = false; try { Development.RepairContext(root, report); } catch (InvalidDataException) { blocked = true; } Assert(blocked, "source secret sent"); } finally { Directory.Delete(root, true); } return Task.FromResult(0);
            });
            await Test("autonomous workflow repairs imported source and verifies new version", async () => {
                var root = Temporary(); int generated = 0; CheckReport final = null; var versions = new List<string>();
                try {
                    await DevelopmentWorkflow.Run("build", "Python: тесты", true, (prompt, token) => {
                        if (generated > 0) Assert(prompt.Contains("AssertionError") && prompt.Contains("def add"), "repair has no real errors or sources");
                        var folder = Path.Combine(root, "v" + generated++); Directory.CreateDirectory(folder);
                        File.WriteAllText(Path.Combine(folder, "calc.py"), "def add(a,b): return " + (generated == 1 ? "0" : "a+b"));
                        File.WriteAllText(Path.Combine(folder, "test_calc.py"), "import unittest\nfrom calc import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n"); return Task.FromResult(folder);
                    }, Development.Check, (folder, report) => { versions.Add(folder); final = report; }, CancellationToken.None);
                    Assert(generated == 2 && final.Verified && File.ReadAllText(Path.Combine(root, "v0", "calc.py")).Contains("return 0"), "workflow did not repair or overwrote original");
                } finally { Directory.Delete(root, true); }
            });
            await Test("unchanged repair clears proof and stops autonomous loop", async () => {
                var root = Temporary(); CheckReport visible = null; int count = 0;
                try { File.WriteAllText(Path.Combine(root, "main.py"), "x=1"); await ExpectError(async () => await DevelopmentWorkflow.Run("build", "Python: тесты", true,
                    (prompt, token) => { count++; return Task.FromResult(root); }, (folder, kind, token) => Task.FromResult(new CheckReport { Kind = kind, Output = "Ran 0 tests", NoTests = true }),
                    (folder, report) => visible = report, CancellationToken.None), "те же исходники"); Assert(count == 2 && visible == null, "stale verification retained"); } finally { Directory.Delete(root, true); }
            });
            await Test("selected PC receives exact source and mode; cancelled report never passes", async () => {
                var root = Temporary(); try { File.WriteAllText(Path.Combine(root, "main.py"), "x=1"); var handler = new FakeHandler { Route = async request => {
                    if (request.Method == HttpMethod.Post) { var body = Json.Parse(await request.Content.ReadAsStringAsync()); Assert(Json.Text(body,"target_device_id") == "pc" && Json.Text(body,"mode") == "python_tests" && Json.Text(Json.Map(Json.Get(body,"files")), "main.py") == "x=1", "wrong relay payload"); return FakeHandler.Reply("{\"id\":\"check_test\"}",202); }
                    if (request.Method == HttpMethod.Delete) return FakeHandler.Reply("{}",200);
                    return FakeHandler.Reply("{\"state\":\"completed\",\"report\":{\"exit_code\":0,\"output\":\"cancelled\",\"cancelled\":true}}",200);
                }}; using (var api = Client(handler)) { var report = await new DevelopmentRelay(api).Remote(root, "Python: тесты", "pc", "flow", CancellationToken.None); Assert(!report.Verified && report.Stopped, "cancelled remote check passed"); } } finally { Directory.Delete(root,true); }
            });
            await Test("real CommonJS test imports source and reports failure then pass", async () => {
                var root = Temporary(); try { File.WriteAllText(Path.Combine(root,"index.js"),"exports.add = (a,b) => 0;"); File.WriteAllText(Path.Combine(root,"test_calc.js"),"const test=require('node:test'); const assert=require('node:assert/strict'); const {add}=require('./index'); test('sum',()=>assert.equal(add(2,3),5));");
                    Assert(!(await Development.Check(root,"JavaScript: тесты",CancellationToken.None)).Verified,"broken JS passed"); File.WriteAllText(Path.Combine(root,"index.js"),"exports.add = (a,b) => a+b;"); Assert((await Development.Check(root,"JavaScript: тесты",CancellationToken.None)).Verified,"fixed JS failed");
                } finally { Directory.Delete(root,true); }
            });
            await Test("consenting PC worker executes delivered sources and returns an actual test report", async () => {
                var root = Temporary(); bool claimed = false, allowed = false, reported = false; DevelopmentRelay relay = null;
                try { var handler = new FakeHandler { Route = async request => {
                    var path = request.RequestUri.AbsolutePath;
                    if (path.EndsWith("/report")) { var body = Json.Parse(await request.Content.ReadAsStringAsync()); var report = Json.Map(Json.Get(body, "report")); Assert(Json.Text(body,"lease") == "lease" && Json.Number(report,"exit_code") == 0 && Json.Text(report,"output").Contains("Ran 1 test"), "not an actual report"); reported = true; return FakeHandler.Reply("{}",200); }
                    if (path.EndsWith("/worker")) {
                        var body = Json.Parse(await request.Content.ReadAsStringAsync()); if (!Json.Flag(body,"enabled")) return FakeHandler.Reply("{}",200);
                        if (!claimed) { claimed = true; return FakeHandler.Reply(Json.Encode(new { job = new { id="check_in", requester_device_id="phone", workflow_id="flow", mode="python_tests", lease="lease", files = new Dictionary<string,string> { {"calc.py","def add(a,b): return a+b"}, {"test_calc.py","import unittest\nfrom calc import add\nclass Calc(unittest.TestCase):\n def test_sum(self): self.assertEqual(add(2,3),5)\n"} } } }),200); }
                        return FakeHandler.Reply("{}",200);
                    }
                    return FakeHandler.Reply("{\"state\":\"running\"}",200);
                }};
                using (var api = Client(handler)) { relay = new DevelopmentRelay(api); var run = relay.Enable(root, (job, token) => { allowed = true; return Task.FromResult(true); }, () => true, message => {});
                    var deadline = DateTime.UtcNow.AddSeconds(15); while (!reported && !run.IsCompleted && DateTime.UtcNow < deadline) await Task.Delay(100); await relay.Disable(); await run;
                    Assert(allowed && reported && !relay.Enabled, "PC worker did not finish or stop"); }
                } finally { Directory.Delete(root,true); }
            });
            Console.WriteLine(passed + " desktop tests passed.");
        }
        static async Task Live() {
            var email = "desktop-smoke-" + Guid.NewGuid().ToString("N") + "@example.com";
            var password = Guid.NewGuid().ToString("N") + "aA1!";
            var path = Temporary(); var store = new LocalStore(path);
            using (var api = new ApiClient()) {
                api.SaveSession = store.SaveSession;
                Exception failure = null;
                try {
                    await api.Authenticate(email, password, true, CancellationToken.None);
                    Assert(api.Account.SignedIn, "live registration failed");
                    await api.Authenticate(email, password, false, CancellationToken.None);
                    await api.Get("/v1/subscription", CancellationToken.None);
                    await api.Get("/v1/account/devices", CancellationToken.None);
                    var project = await api.Call("POST", "/v1/assistant/projects", new { name = "Desktop smoke" }, CancellationToken.None);
                    Assert(Json.Text(Json.Map(Json.Get(project, "project")), "id").Length > 0, "project creation failed");
                    var created = await api.Call("POST", "/v1/assistant/tasks", new { title = "Desktop smoke", action_mode = "remind" }, CancellationToken.None);
                    var id = Json.Text(Json.Map(Json.Get(created, "task")), "id"); Assert(id.Length > 0, "task creation failed");
                    await api.Call("PATCH", "/v1/assistant/tasks/" + Uri.EscapeDataString(id), new { status = "completed" }, CancellationToken.None);
                    var note = await api.Call("POST", "/v1/assistant/notes", new { content = "Disposable desktop note", kind = "context" }, CancellationToken.None); Assert(Json.Map(Json.Get(note, "note")).Count > 0, "note creation failed");
                    var memory = await api.Call("POST", "/v1/memories", new { title = "Desktop smoke", content = "Disposable test memory" }, CancellationToken.None); var memoryId = Json.Text(Json.Map(Json.Get(memory, "memory")), "id");
                    Assert(memoryId.Length > 0, "memory creation failed"); await api.Call("PATCH", "/v1/memories/" + Uri.EscapeDataString(memoryId), new { content = "Updated disposable memory" }, CancellationToken.None); await api.Call("DELETE", "/v1/memories/" + Uri.EscapeDataString(memoryId), null, CancellationToken.None);
                    await api.Call("PUT", "/v1/notification-preferences", new { reminders_enabled = true, proactive_enabled = false, quiet_hours_enabled = false, timezone = "Europe/Moscow", quiet_start = "22:00", quiet_end = "08:00" }, CancellationToken.None);
                    await api.Get("/v1/assistant/reminders", CancellationToken.None); await api.Get("/v1/assistant/inbox?unread_only=true", CancellationToken.None);
                    var export = await api.Download("/v1/account/export", 50 * 1024 * 1024, CancellationToken.None); Assert(export.Length > 0, "account export failed"); Array.Clear(export, 0, export.Length);
                    Console.WriteLine("PASS live account, subscription, devices, tasks");
                    Console.WriteLine("PASS live login, notes, memory CRUD, notification preferences, account export");
                    var result = await api.Run("Создай DOCX с названием «Проверка ПК» и одним абзацем «Тест нового клиента».", null, null, CancellationToken.None); Assert(result.Length > 0, "empty live answer");
                    var pending = await api.Get("/v1/device-files", CancellationToken.None); var items = Json.Rows(pending, "data").ToList(); Assert(items.Count > 0, "no device file created");
                    foreach (var item in items) { var file = await store.Receive(api, item, CancellationToken.None); Assert(File.Exists(file) && new FileInfo(file).Length > 0, "local save failed"); }
                    Assert(!Json.Rows(await api.Get("/v1/device-files", CancellationToken.None), "data").Any(), "ACK did not clear server file");
                    Assert(Json.Rows(await api.Get("/v1/sessions/" + Uri.EscapeDataString(api.SessionId) + "/messages", CancellationToken.None), "messages").Any(), "history missing");
                    Console.WriteLine("PASS live SSE, history, local file integrity, server ACK");
                    var speech = await api.Speech("Проверка клиента", CancellationToken.None); Assert(speech.Length > 100, "empty TTS"); Array.Clear(speech, 0, speech.Length); Console.WriteLine("PASS live TTS response (playback not tested)");
                } catch (Exception error) { failure = error; }
                if (api.Account.SignedIn) { await api.Call("DELETE", "/v1/account", new { confirmation = "DELETE_MY_ACCOUNT" }, CancellationToken.None); Console.WriteLine("Disposable account deleted."); }
                Directory.Delete(path, true);
                if (failure != null) throw failure;
            }
        }
        public static int Main(string[] args) { try { System.Net.ServicePointManager.SecurityProtocol = System.Net.SecurityProtocolType.Tls12; if (args.Contains("--live")) Live().GetAwaiter().GetResult(); else RunAll().GetAwaiter().GetResult(); return 0; } catch (Exception error) { Console.WriteLine("FAIL " + error.GetType().Name + ": " + error.Message + " | " + error.GetBaseException().Message); return 1; } }
    }
}
