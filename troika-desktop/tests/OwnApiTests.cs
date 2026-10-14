using System;
using System.IO;
using System.Net.Http;
using System.Text;
using Troika.Desktop;
class OwnApiTests {
    static void Main() {
        var root = Path.Combine(Path.GetTempPath(), "troika-personal-" + Guid.NewGuid().ToString("N"));
        try {
            var store = new PersonalProviderStore(root);
            string key = "personal-test-key-1234567890";
            store.Save("a@example.invalid", "openrouter", "openrouter/free", key);
            var file = Directory.GetFiles(Path.Combine(root, "personal-api"))[0];
            if (Encoding.UTF8.GetString(File.ReadAllBytes(file)).Contains(key)) throw new Exception("Key stored as plaintext");
            using (var request = new HttpRequestMessage(HttpMethod.Post, "https://example.invalid/v1/runs")) {
                store.Apply(request, "b@example.invalid");
                if (request.Headers.Contains("X-Troika-Provider-Key")) throw new Exception("Another account's key was attached");
                store.Apply(request, "a@example.invalid");
                if (!request.Headers.Contains("X-Troika-Provider-Key")) throw new Exception("Personal key missing");
            }
            File.WriteAllBytes(file, new byte[] { 1, 2, 3 });
            bool blocked = false;
            try { store.Load("a@example.invalid"); } catch (InvalidOperationException) { blocked = true; }
            if (!blocked) throw new Exception("Corrupt personal storage fell back");
            Console.WriteLine("2 personal API checks passed: encrypted account ownership and failed decryption blocks fallback.");
        } finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
