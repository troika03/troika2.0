using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace Troika.Desktop {
    public sealed class DevelopmentCheckpoints {
        private readonly LocalStore store;
        public DevelopmentCheckpoints(LocalStore store) { this.store = store; }
        private string PathFor(string owner, string project) {
            if (!Regex.IsMatch(project, "^run_[a-f0-9]{32}$")) throw new InvalidDataException("Некорректный проект.");
            return Path.Combine(store.Root, "checkpoints", LocalStore.Hash(Encoding.UTF8.GetBytes(owner.ToLowerInvariant())), project + ".dat");
        }
        public Dictionary<string, object> Read(string owner, string project) {
            foreach (var path in new[] { PathFor(owner, project), PathFor(owner, project)+".previous" }) {
                try {
                    var bytes = ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.CurrentUser);
                    try { return Validate(Json.Parse(Encoding.UTF8.GetString(bytes))); }
                    finally { Array.Clear(bytes, 0, bytes.Length); }
                } catch { /* Try the last complete encrypted copy. */ }
            }
            return null;
        }
        private static Dictionary<string, object> Validate(Dictionary<string, object> value) {
            var payload = Convert.FromBase64String(Json.Text(value, "payload"));
            if (payload.Length > 2500000 || LocalStore.Hash(payload) != Json.Text(value, "digest")) throw new InvalidDataException("Контрольная копия повреждена.");
            var state = Json.Parse(Encoding.UTF8.GetString(payload));
            if (Json.Number(state, "version") != 1) throw new InvalidDataException("Неизвестная контрольная копия.");
            value["checkpoint"] = state;
            return value;
        }
        public void Save(string owner, string project, Dictionary<string, object> value) {
            Validate(value);
            var saved = new Dictionary<string, object>(value); saved.Remove("checkpoint");
            var bytes = Encoding.UTF8.GetBytes(Json.Encode(saved));
            try {
                var path=PathFor(owner,project);
                if (File.Exists(path)) WriteAtomic(path+".previous",File.ReadAllBytes(path));
                WriteAtomic(path, ProtectedData.Protect(bytes, null, DataProtectionScope.CurrentUser));
            }
            finally { Array.Clear(bytes, 0, bytes.Length); }
        }
        private static void WriteAtomic(string path, byte[] bytes) {
            var folder=Path.GetDirectoryName(path); Directory.CreateDirectory(folder);
            // A short sibling filename keeps .NET Framework paths below MAX_PATH.
            var temporary=Path.Combine(folder,Guid.NewGuid().ToString("N")+".tmp");
            try {
                using (var stream=new FileStream(temporary,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { stream.Write(bytes,0,bytes.Length); stream.Flush(true); }
                if (File.Exists(path)) File.Replace(temporary,path,null); else File.Move(temporary,path);
            } finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
    }
}
