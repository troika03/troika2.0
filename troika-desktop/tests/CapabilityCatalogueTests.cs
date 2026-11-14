using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    sealed class CatalogueHandler : HttpMessageHandler {
        public Func<HttpRequestMessage, Task<HttpResponseMessage>> Route;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) { return Route(request); }
        public static HttpResponseMessage Reply(string value, int status) { return new HttpResponseMessage((HttpStatusCode)status) { Content = new StringContent(value, Encoding.UTF8, "application/json") }; }
    }
    static class CapabilityCatalogueTests {
        static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
        static string Snapshot(bool enabled) { return Json.Encode(new { @object = "troika.capabilities", capabilities = new[] { new { id = "web", title = "Поиск", enabled, available = true } } }); }
        static async Task Run() {
            bool patchSeen = false;
            var handler = new CatalogueHandler { Route = async request => {
                Assert(request.RequestUri.AbsolutePath == "/v1/account/capabilities", "wrong route");
                Assert(request.Headers.Authorization.Parameter == "trk_live_test", "missing account auth");
                if (request.Method.Method == "PATCH") {
                    var body = Json.Parse(await request.Content.ReadAsStringAsync());
                    var patch = Json.Map(Json.Get(body, "enabled"));
                    Assert(body.Count == 1 && patch.Count == 1 && object.Equals(Json.Get(patch, "web"), false), "wrong patch or supplied owner");
                    patchSeen = true; return CatalogueHandler.Reply(Snapshot(false), 200);
                }
                return CatalogueHandler.Reply(Snapshot(true), 200);
            }};
            using (var api = new ApiClient(handler, "https://example.test") { Account = new AccountSession {
                Token = "trk_live_test", RefreshToken = "trk_refresh_test", HomeSession = "home_test", ExpiresAt = 9999999999 } }) {
                var service = new CapabilityCatalogueService(api);
                var current = await service.Load(CancellationToken.None);
                Assert(Json.Flag(current[0], "enabled"), "GET snapshot missing");
                current = await service.SetEnabled("web", false, CancellationToken.None);
                Assert(patchSeen && !Json.Flag(current[0], "enabled"), "PATCH ignored server snapshot");
                handler.Route = request => Task.FromResult(CatalogueHandler.Reply("{}", 503));
                bool failed = false;
                try { await service.SetEnabled("web", true, CancellationToken.None); } catch (ApiException) { failed = true; }
                Assert(failed && !Json.Flag(current[0], "enabled"), "failure changed previous snapshot");
            }
            bool malformed = false;
            try { CapabilityCatalogueService.Parse(Json.Parse("{\"object\":\"troika.capabilities\",\"capabilities\":[{\"id\":\"web\",\"title\":\"Search\",\"enabled\":\"false\",\"available\":true}]}")); }
            catch (System.IO.InvalidDataException) { malformed = true; }
            Assert(malformed, "malformed catalogue accepted");
            await Extensions();
            Console.WriteLine("5 capability catalogue checks passed: authenticated snapshot/patch, failed save, malformed response, skill patch, old-server fallback.");
        }
        static string Extensions(bool connected) { return Json.Encode(new { @object = "troika.extensions",
            skills = new[] { new { id = "creative/humanizer", title = "Живой текст", description = "Текст", connectable = true, connected, reason = "" } },
            mcp = new[] { new { id = "linear", title = "Linear", description = "Issues", connectable = false, connected = false, reason = "Нужен вход" } },
            tools = new[] { new { id = "web", title = "Поиск", enabled = true, available = true } } }); }
        static async Task Extensions() {
            bool skillPatch = false, mcpPatch = false;
            var handler = new CatalogueHandler { Route = async request => {
                Assert(request.RequestUri.AbsolutePath == "/v1/account/extensions", "wrong extension route");
                if (request.Method.Method == "PATCH") {
                    var body = Json.Parse(await request.Content.ReadAsStringAsync());
                    if (body.ContainsKey("mcp")) {
                        Assert(body.Count == 1 && object.Equals(Json.Get(Json.Map(Json.Get(body, "mcp")), "deepwiki"), true), "wrong MCP patch");
                        mcpPatch = true; return CatalogueHandler.Reply(Extensions(true), 200);
                    }
                    var patch = Json.Map(Json.Get(body, "skills"));
                    Assert(body.Count == 1 && object.Equals(Json.Get(patch, "creative/humanizer"), true), "wrong skill patch");
                    skillPatch = true; return CatalogueHandler.Reply(Extensions(true), 200);
                }
                return CatalogueHandler.Reply(Extensions(false), 200);
            }};
            using (var api = new ApiClient(handler, "https://example.test") { Account = new AccountSession {
                Token = "trk_live_test", RefreshToken = "trk_refresh_test", HomeSession = "home_test", ExpiresAt = 9999999999 } }) {
                var service = new CapabilityCatalogueService(api);
                var current = await service.LoadCatalogue(CancellationToken.None);
                Assert(!current.Legacy && current.Mcp.Count == 1 && !Json.Flag(current.Skills[0], "connected"), "extension snapshot missing");
                Assert(current.ExtensionsAllowed, "missing plan flag must keep old servers usable");
                Assert(!CapabilityCatalogueService.ParseCatalogue(Json.Parse("{\"object\":\"troika.extensions\",\"extensions_allowed\":false,\"skills\":[],\"mcp\":[],\"tools\":[]}")).ExtensionsAllowed, "Pro lock ignored");
                current = await service.SetSkillConnected("creative/humanizer", true, CancellationToken.None);
                Assert(skillPatch && Json.Flag(current.Skills[0], "connected"), "skill patch ignored server snapshot");
                await service.SetMcpConnected("deepwiki", true, CancellationToken.None);
                Assert(mcpPatch, "MCP patch not sent");
                handler.Route = request => Task.FromResult(request.RequestUri.AbsolutePath == "/v1/account/extensions"
                    ? CatalogueHandler.Reply("{}", 404) : CatalogueHandler.Reply(Snapshot(true), 200));
                var legacy = await service.LoadCatalogue(CancellationToken.None);
                Assert(legacy.Legacy && legacy.Tools.Count == 1, "old server fallback missing");
                bool refused = false;
                try { await service.SetSkillConnected("creative/humanizer", true, CancellationToken.None); } catch (InvalidOperationException) { refused = true; }
                Assert(refused, "old server pretended to connect a skill");
            }
        }
        public static int Main() { try { Run().GetAwaiter().GetResult(); return 0; } catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; } }
    }
}
