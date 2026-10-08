using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
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
        public static List<Dictionary<string, object>> Parse(Dictionary<string, object> value) {
            if (Json.Text(value, "object") != "troika.capabilities" || !(Json.Get(value, "capabilities") is object[]))
                throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            var items = Json.Rows(value, "capabilities").ToList();
            if (items.Count != ((object[])Json.Get(value, "capabilities")).Length || items.Any(item =>
                Json.Text(item, "id").Length == 0 || Json.Text(item, "title").Length == 0 ||
                !(Json.Get(item, "enabled") is bool) || !(Json.Get(item, "available") is bool)))
                throw new InvalidDataException("Сервер вернул некорректный каталог возможностей.");
            return items;
        }
    }
}
