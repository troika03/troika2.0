using System;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed class DevelopmentWorkflow {
        public const string ModelReview = "Модель: ревью и исправление";
        public static string ModelPrompt(string task) {
            return "Загрузи capability development и вызови troika_create_project с title и task. В task передай полную задачу ниже. API-разработчик сам составит план, напишет каждый файл, проверит весь проект моделью и исправит ошибки до трёх раз. Не создавай короткую заготовку сам. Не спрашивай устройство проверки. Не запускай тесты. Верни ZIP с MODEL_REVIEW.md. Задача пользователя: " + task;
        }
        public static string ModelReviewStatus(string folder) {
            var path = System.IO.Path.Combine(folder, "troika-project.json");
            if (!System.IO.File.Exists(path)) return "Проект сохранён. Ревью модели не подтверждено.";
            var manifest = Json.Parse(System.IO.File.ReadAllText(path));
            var review = Json.Map(Json.Get(manifest, "review"));
            if (Json.Text(review, "method") != "api_model_review") return "Проект сохранён. Ревью модели не подтверждено.";
            var result = Json.Text(review, "status") == "passed" ? "Проект сохранён. Модель проверила исходники." : "Проект сохранён. Ревью модели нашло ошибки; смотрите отчёт.";
            switch (Json.Text(review, "execution")) {
                case "passed": result += " Тесты прошли в изолированной среде."; break;
                case "failed": result += " Тесты завершились с ошибками."; break;
                case "not_run": result += " Тесты не запускались."; break;
                default: result += " Исполнение тестов не подтверждено."; break;
            }
            if (Json.Text(review,"visual_review")=="passed") result += " Визуальная проверка пройдена.";
            return result;
        }
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
        public static string Portable(string kind) { return "Сохрани назначение и требования: веб-приложению нужен браузерный интерфейс HTML/CSS и работающая логика. Среда проверки не заменяет интерфейс консольной программой. troika_create_project только упаковывает полный код, который ты напишешь, README.md и тесты; Hello World и заглушки не выполняют задачу. " + (kind.StartsWith("Python") ? "Python: только стандартная библиотека, unittest test_*.py; тесты импортируют настоящий код проекта. Без pip и внешних сервисов." : "JavaScript: CommonJS index.js, test_*.js с node:test и node:assert/strict, только test(name, callback). Тесты импортируют настоящий код. Без npm, сети и внешних пакетов."); }
    }
}
