using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    // Skills, MCP servers and product tools of the account. Skills and Mcp are
    // null when the server predates the extension catalogue.
    public sealed class CatalogueSnapshot {
        public List<Dictionary<string, object>> Skills;
        public List<Dictionary<string, object>> Mcp;
        public List<Dictionary<string, object>> Tools;
        public bool Legacy { get { return Skills == null; } }
    }

    public sealed class CapabilityCatalogueService {
        private readonly ApiClient api;
        public CapabilityCatalogueService(ApiClient client) { api = client; }
        public async Task<List<Dictionary<string, object>>> Load(CancellationToken cancellation) {
            return Parse(await api.Get("/v1/account/capabilities", cancellation));
        }
        public async Task<List<Dictionary<string, object>>> SetEnabled(string id, bool enabled, CancellationToken cancellation) {
            if (string.IsNullOrWhiteSpace(id)) throw new ArgumentException("Выберите возможность.");
            return Parse(await api.Call("PATCH", "/v1/account/capabilities",
                new { enabled = new Dictionary<string, bool> { { id, enabled } } }, cancellation));
        }
        public async Task<CatalogueSnapshot> LoadCatalogue(CancellationToken cancellation) {
            try { return ParseCatalogue(await api.Get("/v1/account/extensions", cancellation)); }
            catch (ApiException error) { if (error.Status != 404) throw; }
            // Older server: only the tool switches exist.
            return new CatalogueSnapshot { Tools = await Load(cancellation) };
        }
        public Task<CatalogueSnapshot> SetSkillConnected(string id, bool connected, CancellationToken cancellation) {
            if (string.IsNullOrWhiteSpace(id)) throw new ArgumentException("Выберите навык.");
            return Connect(new { skills = new Dictionary<string, bool> { { id, connected } } }, cancellation);
        }
        public Task<CatalogueSnapshot> SetMcpConnected(string id, bool connected, CancellationToken cancellation) {
            if (string.IsNullOrWhiteSpace(id)) throw new ArgumentException("Выберите сервер MCP.");
            return Connect(new { mcp = new Dictionary<string, bool> { { id, connected } } }, cancellation);
        }
        // Starts browser sign-in (token == null) or saves a personal token.
        // Returns status "connected" or "waiting" with flow and https URL.
        public async Task<Dictionary<string, object>> ConnectService(string id, string token, CancellationToken cancellation) {
            if (string.IsNullOrWhiteSpace(id)) throw new ArgumentException("Выберите сервис.");
            object body = token == null ? (object)new Dictionary<string, object>() : new { token };
            var result = await api.Call("POST", "/v1/account/services/" + Uri.EscapeDataString(id) + "/connect", body, cancellation);
            var status = Json.Text(result, "status");
            if (status == "waiting") {
                Uri address;
                if (!Uri.TryCreate(Json.Text(result, "authorization_url"), UriKind.Absolute, out address) || address.Scheme != "https" || Json.Text(result, "flow").Length == 0)
                    throw new InvalidDataException("Сервер вернул некорректный адрес входа.");
            } else if (status != "connected") throw new InvalidDataException("Сервер вернул некорректный ответ.");
            return result;
        }
        public async Task<string> FlowStatus(string flow, CancellationToken cancellation) {
            var result = await api.Get("/v1/account/services/flows/" + Uri.EscapeDataString(flow), cancellation);
            var status = Json.Text(result, "status");
            return status.Length == 0 ? "expired" : status;
        }
        private async Task<CatalogueSnapshot> Connect(object patch, CancellationToken cancellation) {
            try {
                return ParseCatalogue(await api.Call("PATCH", "/v1/account/extensions", patch, cancellation));
            } catch (ApiException error) {
                if (error.Status == 404) throw new InvalidOperationException("Сервер пока не поддерживает подключение навыков и MCP.");
                if (error.Status == 403) throw new InvalidOperationException("Это нельзя подключить в облаке Тройки.");
                throw;
            }
        }
        public async Task<CatalogueSnapshot> SetToolEnabled(string id, bool enabled, CancellationToken cancellation) {
            if (string.IsNullOrWhiteSpace(id)) throw new ArgumentException("Выберите возможность.");
            try {
                return ParseCatalogue(await api.Call("PATCH", "/v1/account/extensions",
                    new { capabilities = new Dictionary<string, bool> { { id, enabled } } }, cancellation));
            } catch (ApiException error) { if (error.Status != 404) throw; }
            return new CatalogueSnapshot { Tools = await SetEnabled(id, enabled, cancellation) };
        }
        public static List<Dictionary<string, object>> Parse(Dictionary<string, object> value) {
            if (Json.Text(value, "object") != "troika.capabilities" || !(Json.Get(value, "capabilities") is object[]))
                throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            return Tools(value, "capabilities");
        }
        public static CatalogueSnapshot ParseCatalogue(Dictionary<string, object> value) {
            if (Json.Text(value, "object") != "troika.extensions")
                throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            return new CatalogueSnapshot { Skills = Entries(value, "skills"), Mcp = Entries(value, "mcp"), Tools = Tools(value, "tools") };
        }
        private static List<Dictionary<string, object>> Tools(Dictionary<string, object> value, string key) {
            var raw = Json.Get(value, key) as object[];
            if (raw == null) throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            var items = Json.Rows(value, key).ToList();
            if (items.Count != raw.Length || items.Any(item =>
                Json.Text(item, "id").Length == 0 || Json.Text(item, "title").Length == 0 ||
                !(Json.Get(item, "enabled") is bool) || !(Json.Get(item, "available") is bool)))
                throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            return items;
        }
        private static List<Dictionary<string, object>> Entries(Dictionary<string, object> value, string key) {
            var raw = Json.Get(value, key) as object[];
            if (raw == null) throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            var items = Json.Rows(value, key).ToList();
            if (items.Count != raw.Length || items.Any(item =>
                Json.Text(item, "id").Length == 0 || Json.Text(item, "title").Length == 0 ||
                !(Json.Get(item, "connectable") is bool) || !(Json.Get(item, "connected") is bool)))
                throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            return items;
        }
    }
}
