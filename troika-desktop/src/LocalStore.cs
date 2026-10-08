using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed class LocalStore {
        public readonly string Root;
        public LocalStore() : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TroikaDesktop")) { }
        public LocalStore(string root) { Root = Path.GetFullPath(root); Directory.CreateDirectory(Root); }
        public static string Hash(byte[] data) { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant(); }
        public AccountSession LoadSession() {
            try {
                var data = ProtectedData.Unprotect(File.ReadAllBytes(Path.Combine(Root, "session.dat")), null, DataProtectionScope.CurrentUser);
                var value = Json.Parse(Encoding.UTF8.GetString(data));
                Array.Clear(data, 0, data.Length);
                return new AccountSession { Email = Json.Text(value, "email"), Token = Json.Text(value, "token"), RefreshToken = Json.Text(value, "refresh_token"), ExpiresAt = Json.Number(value, "expires_at"), HomeSession = Json.Text(value, "home_session"), DeviceId = Json.Text(value, "device_id") };
            } catch { return new AccountSession(); }
        }
        public void SaveSession(AccountSession account) {
            var value = Json.Encode(new { email = account.Email, token = account.Token, refresh_token = account.RefreshToken, expires_at = account.ExpiresAt, home_session = account.HomeSession, device_id = account.DeviceId });
            var data = Encoding.UTF8.GetBytes(value);
            try { WriteAtomic(Path.Combine(Root, "session.dat"), ProtectedData.Protect(data, null, DataProtectionScope.CurrentUser)); }
            finally { Array.Clear(data, 0, data.Length); }
        }
        public void ForgetSession() { var file = Path.Combine(Root, "session.dat"); if (File.Exists(file)) File.Delete(file); }
        public static void WriteAtomic(string path, byte[] data) {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var temporary = path + "." + Guid.NewGuid().ToString("N") + ".part";
            try {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { stream.Write(data, 0, data.Length); stream.Flush(true); }
                if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
            } finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        public string FilesFolder(string owner) { return Path.Combine(Root, "files", Hash(Encoding.UTF8.GetBytes(owner.ToLowerInvariant()))); }
        public static string SafeName(string name) {
            if (string.IsNullOrWhiteSpace(name) || name != Path.GetFileName(name) || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || name.EndsWith(".") || name.EndsWith(" ") || name.Length > 140) throw new InvalidDataException("Недопустимое имя файла.");
            var stem = Path.GetFileNameWithoutExtension(name).ToUpperInvariant();
            if (new[] { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" }.Contains(stem)) throw new InvalidDataException("Недопустимое имя файла.");
            return name;
        }
        public async Task<string> Receive(ApiClient api, Dictionary<string, object> item, CancellationToken cancellation) {
            var id = Json.Text(item, "id");
            if (!System.Text.RegularExpressions.Regex.IsMatch(id, "^delivery_[a-f0-9]{32}$")) throw new InvalidDataException("Недопустимый идентификатор передачи.");
            var name = SafeName(Json.Text(item, "filename"));
            var folder = Path.Combine(FilesFolder(api.Account.Email), id);
            var path = Path.Combine(folder, name);
            var expectedHash = Json.Text(item, "sha256");
            var size = Json.Number(item, "size");
            if (size <= 0 || size > 50 * 1024 * 1024 || !System.Text.RegularExpressions.Regex.IsMatch(expectedHash, "^[a-f0-9]{64}$")) throw new InvalidDataException("Некорректные сведения о файле.");
            if (!File.Exists(path) || new FileInfo(path).Length != size || Hash(File.ReadAllBytes(path)) != expectedHash) {
                var bytes = await api.Download("/v1/device-files/" + id, 50 * 1024 * 1024, cancellation);
                if (bytes.Length != size || Hash(bytes) != expectedHash) throw new InvalidDataException("Файл повреждён. Получение не подтверждено серверу.");
                WriteAtomic(path, bytes);
            }
            // Durable local file comes before ACK. Retry recognizes a saved delivery after a lost ACK.
            await api.Call("POST", "/v1/device-files/" + id + "/received", new { }, cancellation);
            return path;
        }
        public IEnumerable<string> Files(string owner) {
            var folder = FilesFolder(owner);
            return Directory.Exists(folder) ? Directory.EnumerateDirectories(folder, "delivery_*").SelectMany(p => Directory.EnumerateFiles(p)).Where(p => !p.EndsWith(".part")).OrderByDescending(File.GetLastWriteTimeUtc) : Enumerable.Empty<string>();
        }
        public Dictionary<string, object> Settings() { try { return Json.Parse(File.ReadAllText(Path.Combine(Root, "settings.json"))); } catch { return new Dictionary<string, object>(); } }
        public void SaveSettings(object value) { WriteAtomic(Path.Combine(Root, "settings.json"), Encoding.UTF8.GetBytes(Json.Encode(value))); }
    }
}
