using System;
using System.IO;
using System.Text;

namespace Troika.Desktop {
    public static class PaymentKeys {
        private static string Location(string root, string owner, string sku) {
            if (String.IsNullOrWhiteSpace(owner) || !(sku == "plus" || sku == "pro" || sku == "top_up")) throw new ArgumentException("Invalid payment owner or offer.");
            var directory = Path.Combine(root, "payment-intents"); Directory.CreateDirectory(directory);
            return Path.Combine(directory, LocalStore.Hash(Encoding.UTF8.GetBytes(owner + "\n" + sku)) + ".key");
        }
        public static string LoadOrCreate(string root, string owner, string sku) {
            string path = Location(root, owner, sku);
            if (!File.Exists(path)) {
                try {
                    using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                        byte[] value = Encoding.ASCII.GetBytes(Guid.NewGuid().ToString()); stream.Write(value, 0, value.Length); stream.Flush(true);
                    }
                } catch (IOException) { if (!File.Exists(path)) throw; }
            }
            string key = File.ReadAllText(path); Guid parsed;
            if (!Guid.TryParse(key, out parsed)) throw new InvalidOperationException("Не удалось восстановить незавершённый платёж. Нужна проверка оплаты перед новой покупкой.");
            return key;
        }
        public static void Complete(string root, string owner, string sku, string key) {
            string path = Location(root, owner, sku);
            if (File.Exists(path) && File.ReadAllText(path) == key) File.Delete(path);
        }
    }
}
