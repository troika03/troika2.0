using System;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed class DevelopmentWorkflow {
        public static async Task Run(string prompt, string kind, bool execute, Func<string, CancellationToken, Task<string>> generate, Func<string, string, CancellationToken, Task<CheckReport>> check, Action<string, CheckReport> version, CancellationToken token) {
            string folder = "", previous = "";
            for (int attempt = 0; attempt <= 3; attempt++) {
                token.ThrowIfCancellationRequested();
                folder = await generate(prompt, token); token.ThrowIfCancellationRequested(); version(folder, null);
                if (!execute) return;
                var signature = LocalStore.Hash(System.Text.Encoding.UTF8.GetBytes(Json.Encode(Development.Sources(folder))));
                if (signature == previous) throw new InvalidOperationException("ИИ вернул те же исходники. Исправления остановлены; новая версия не проверена."); previous = signature;
                var report = await check(folder, kind, token); token.ThrowIfCancellationRequested(); version(folder, report);
                if (report.Verified || report.Stopped || report.TimedOut || attempt == 3) return;
                prompt = Development.RepairContext(folder, report) + "\nСохрани исходное назначение проекта. Обязательно включи работающие тесты и PLAN.md. " + Portable(kind);
            }
        }
        public static string Portable(string kind) { return kind.StartsWith("Python") ? "Python: только стандартная библиотека, unittest test_*.py; тесты импортируют настоящий код проекта. Без pip и внешних сервисов." : "JavaScript: CommonJS index.js, test_*.js с node:test и node:assert/strict, только test(name, callback). Тесты импортируют настоящий код. Без npm, сети и внешних пакетов."; }
    }
}
