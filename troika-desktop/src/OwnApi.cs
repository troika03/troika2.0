using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;

namespace Troika.Desktop {
    public sealed class PersonalProviderStore {
        private readonly string root;
        public PersonalProviderStore(string root) { this.root = root; }
        private string PathFor(string owner) { return Path.Combine(root, "personal-api", LocalStore.Hash(Encoding.UTF8.GetBytes(owner.ToLowerInvariant())) + ".dat"); }
        public Dictionary<string, object> Load(string owner) {
            var path = PathFor(owner);
            if (!File.Exists(path)) return new Dictionary<string, object>();
            try {
                var bytes = ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.CurrentUser);
                try { return Json.Parse(Encoding.UTF8.GetString(bytes)); }
                finally { Array.Clear(bytes, 0, bytes.Length); }
            } catch { throw new InvalidOperationException("Личный API-ключ недоступен. Ключ Тройки не использован; подключите свой ключ снова."); }
        }
        public void Save(string owner, string provider, string model, string key) {
            if (owner.Length == 0 || !new[] { "openrouter", "openai" }.Contains(provider) || model.Length == 0 || model.Length > 200 || model.Any(char.IsWhiteSpace) || key.Length < 16 || key.Length > 512 || key.Any(char.IsWhiteSpace)) throw new ArgumentException("Проверьте провайдера, модель и API-ключ.");
            var bytes = Encoding.UTF8.GetBytes(Json.Encode(new { provider, model, key }));
            try { LocalStore.WriteAtomic(PathFor(owner), ProtectedData.Protect(bytes, null, DataProtectionScope.CurrentUser)); }
            finally { Array.Clear(bytes, 0, bytes.Length); }
        }
        public void Disable(string owner) { var p = PathFor(owner); if (File.Exists(p)) File.Delete(p); }
        public void Apply(HttpRequestMessage request, string owner) {
            var value = Load(owner); if (value.Count == 0) return;
            request.Headers.Add("X-Troika-Provider", Json.Text(value, "provider"));
            request.Headers.Add("X-Troika-Provider-Model", Json.Text(value, "model"));
            request.Headers.Add("X-Troika-Provider-Key", Json.Text(value, "key"));
        }
    }
}
