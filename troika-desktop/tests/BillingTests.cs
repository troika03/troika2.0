using System;
using System.IO;
using Troika.Desktop;

class BillingTests {
    static void Assert(bool value) { if (!value) throw new Exception("Payment key invariant failed."); }
    static int Main() {
        var root = Path.Combine(Path.GetTempPath(), "troika-payment-" + Guid.NewGuid().ToString("N"));
        try {
            string key = PaymentKeys.LoadOrCreate(root, "owner@example.test", "plus");
            Assert(key == PaymentKeys.LoadOrCreate(root, "owner@example.test", "plus"));
            Assert(key != PaymentKeys.LoadOrCreate(root, "other@example.test", "plus"));
            Assert(key != PaymentKeys.LoadOrCreate(root, "owner@example.test", "pro"));
            PaymentKeys.Complete(root, "owner@example.test", "plus", "different-key");
            Assert(key == PaymentKeys.LoadOrCreate(root, "owner@example.test", "plus"));
            PaymentKeys.Complete(root, "owner@example.test", "plus", key);
            Assert(key != PaymentKeys.LoadOrCreate(root, "owner@example.test", "plus"));
            Console.WriteLine("2 billing checks passed: durable account/offer identity and explicit completion.");
            return 0;
        } finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
