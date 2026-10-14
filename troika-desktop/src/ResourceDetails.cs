using System.Collections.Generic;
using System.Linq;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private void ShowResourceDetails(Dictionary<string, object> subscription) {
            panelContent.Children.Clear(); panelTitle.Text = "Расход AI-токенов";
            panelContent.Children.Add(Label("Короткое сообщение тоже передаёт модели память, историю и инструменты. Списывается подтверждённый расход, оставшийся резерв возвращается.", 13, muted));
            foreach (var operation in Json.Rows(subscription, "recent_operations").Take(10)) {
                var usage = Json.Map(Json.Get(operation, "usage")); var tokens = Json.Map(Json.Get(usage, "tokens")); var service = Json.Map(Json.Get(usage, "service_usage"));
                string charged = Json.Text(operation, "charged_tokens");
                panelContent.Children.Add(Label(charged.Length == 0 ? "Расход уточняется · резерв " + Json.Text(operation, "reserved_tokens") : "Списано " + charged + " расчётных AI-токенов", 14, text));
                if (Json.Text(service, "tokens_upper_bound") == "1") panelContent.Children.Add(Label("Бесплатная модель передала разные счётчики: ответ " + Json.Text(service, "reported_completion_tokens") + ", рассуждения " + Json.Text(service, "reported_reasoning_tokens") + ". Вход и ответ учитываются без повторного сложения рассуждений.", 12, muted));
                else if (tokens.Count > 0) panelContent.Children.Add(Label("Токены модели: вход " + Json.Text(tokens, "input_tokens") + ", cache " + Json.Text(tokens, "cache_read_tokens") + ", cache write " + Json.Text(tokens, "cache_write_tokens") + ", ответ " + Json.Text(tokens, "output_tokens") + ". Reasoning " + Json.Text(tokens, "reasoning_tokens") + " уже входит в ответ.", 12, muted));
                if (service.Count > 0) panelContent.Children.Add(Label("Расход по коэффициентам: " + Json.Text(service, "cost_rub") + " ₽ · единиц услуги: " + Json.Text(service, "units"), 12, muted));
                panelContent.Children.Add(Label("Версия коэффициентов: " + Json.Text(operation, "pricing_version"), 12, muted)); Gap();
            }
            AddPanelButton("Вернуться в аккаунт", () => OpenPanel("Аккаунт"), false);
        }
    }
}
