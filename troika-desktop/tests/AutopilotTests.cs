using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    sealed class AutopilotHandler : HttpMessageHandler {
        public Func<HttpRequestMessage, Task<HttpResponseMessage>> Route;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) { return Route(request); }
        public static HttpResponseMessage Reply(string value, int status = 200) { return new HttpResponseMessage((HttpStatusCode)status) { Content = new StringContent(value, Encoding.UTF8, "application/json") }; }
    }
    static class AutopilotTests {
        static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
        static string Snapshot(bool pro, string state, int reportId, string report) { return Json.Encode(new { enabled = pro, projects = new[] { new { run_id = "project", title = "Example", status = state, stage = state, workers = new object[0], reports = reportId == 0 ? new object[0] : new object[] { new { id = reportId, stage = state, text = report } } } } }); }
        static async Task Run(string folder) {
            bool pro = true, unavailable = false, failPost = true; int posts = 0; string state = "running", report = "Plan ready"; int reportId = 1; var keys = new List<string>();
            var handler = new AutopilotHandler { Route = async request => {
                if (request.Method.Method == "GET") return AutopilotHandler.Reply(unavailable ? "{}" : Snapshot(pro, state, reportId, report), unavailable ? 404 : 200);
                if (request.RequestUri.AbsolutePath.EndsWith("/stop")) { Assert(request.RequestUri.AbsolutePath == "/v1/runs/project/stop", "stopped foreground run"); return AutopilotHandler.Reply("{}"); }
                var body = Json.Parse(await request.Content.ReadAsStringAsync());
                Assert(Json.Text(body, "workflow") == "development" && Json.Flag(body, "free_only"), "wrong workflow");
                Assert(!body.ContainsKey("session_id"), "borrowed foreground session");
                keys.Add(Json.Text(body, "idempotency_key")); posts++;
                if (failPost) { failPost = false; throw new HttpRequestException("Connection interrupted"); }
                return AutopilotHandler.Reply("{\"run_id\":\"project\"}", 202);
            }};
            using (var api = new ApiClient(handler, "https://example.test") { SessionId = "conversation", ActiveRun = "foreground", Account = new AccountSession { Email = "owner@example.com", Token = "trk_live_test", RefreshToken = "trk_refresh_test", HomeSession = "home_test", ExpiresAt = 9999999999 } }) {
                var service = new DevelopmentAutopilot(api, new LocalStore(folder));
                try { await service.Start("Create website", null, CancellationToken.None); } catch (HttpRequestException) { }
                await service.Start("Create website", null, CancellationToken.None);
                Assert(keys.Count == 2 && keys[0] == keys[1], "network retry duplicated project");
                Assert(api.ActiveRun == "foreground" && api.SessionId == "conversation", "foreground context overwritten");
                Assert(service.NextReport(false) == null, "report interrupted conversation");
                state = "completed"; report = "Result ready"; reportId = 2; await service.Refresh(CancellationToken.None);
                var ready = service.NextReport(true); Assert(ready != null && ready.Text == "Example. Result ready", "missing project identity or stale milestone after completion");
                service.ReportSpoken(ready); await service.Refresh(CancellationToken.None); Assert(service.NextReport(true) == null, "report repeated");
                await service.Stop("project", CancellationToken.None); Assert(api.ActiveRun == "foreground", "Stop changed foreground");
                reportId = 3; report = "Updated"; await service.Refresh(CancellationToken.None); service.SetVoice(false); service.SetVoice(true); await service.Refresh(CancellationToken.None); Assert(service.NextReport(true) == null, "muted report replayed");
                unavailable = true; bool blocked = false; try { await service.Start("Legacy server", null, CancellationToken.None); } catch (ApiException) { blocked = true; }
                Assert(blocked && posts == 2, "old server fell back to chat");
                unavailable = false; pro = false; blocked = false; try { await service.Start("Plus plan", null, CancellationToken.None); } catch (InvalidOperationException) { blocked = true; }
                Assert(blocked && posts == 2, "Plus created development Run");
                api.Account = new AccountSession(); await service.Refresh(CancellationToken.None); Assert(service.Projects.Count == 0 && service.Results.Count == 0 && service.NextReport(true) == null, "logout leaked old project");
            }
            Console.WriteLine("8 autopilot checks passed: independent chat, retry identity, idle voice, final coalescing, Stop scope, mute, protocol/Pro gate, account isolation.");
        }
        public static int Main() {
            var folder = Path.Combine(Path.GetTempPath(), "troika-autopilot-test-" + Guid.NewGuid().ToString("N"));
            try { Run(folder).GetAwaiter().GetResult(); return 0; } catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
            finally { if (Directory.Exists(folder)) Directory.Delete(folder, true); }
        }
    }
}
