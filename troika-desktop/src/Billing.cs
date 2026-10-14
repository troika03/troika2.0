using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private bool paymentBusy;
        private void AddBillingOptions(bool enabled, bool verificationEnabled) {
            if (verificationEnabled) AddPanelButton("Подтвердить почту и проверить Welcome", ShowEmailVerification, false);
            panelContent.Children.Add(Label("Free: 500 000 · Plus: 5 000 000 за 790 ₽ · Pro: 10 000 000 за 1 490 ₽ в месяц", 12, muted));
            panelContent.Children.Add(Label("Free — голос, текст, память и дела; поиск до 10 задач, документы до 3, снимки до 5. Plus — документы и небольшие проекты. Pro — сложные задачи и до трёх одновременно.", 12, muted));
            if (!enabled) { panelContent.Children.Add(Label("Продажи откроются после подключения оплаты и проверки всех функций.", 12, muted)); return; }
            AddPanelButton("Plus · 790 ₽/месяц", () => { var task = BuyResource("plus", "Plus · 790 ₽/месяц"); }, false);
            AddPanelButton("Pro · 1 490 ₽/месяц", () => { var task = BuyResource("pro", "Pro · 1 490 ₽/месяц"); }, false);
            AddPanelButton("+1 000 000 токенов · 99 ₽", () => { var task = BuyResource("top_up", "+1 000 000 AI-токенов · 99 ₽"); }, false);
        }
        private void ShowEmailVerification() {
            panelContent.Children.Clear(); panelTitle.Text = "Подтверждение почты";
            panelContent.Children.Add(Label("Код придёт на почту аккаунта. Welcome выдаётся один раз после проверки аккаунта при доступном фонде.", 13, muted));
            var code = new System.Windows.Controls.PasswordBox { MaxLength = 6, Margin = new Thickness(0, 10, 0, 10) };
            panelContent.Children.Add(code); string challenge = "";
            AddPanelButton("Получить код", () => { var task = Safe(async () => {
                var result = await api.Call("POST", "/v1/account/verification/request", new { }, CancellationToken.None);
                if (Json.Flag(result, "verified")) { await api.Call("POST", "/v1/account/verification/welcome", new { }, CancellationToken.None); SetStatus("Почта уже подтверждена. Остаток Welcome — в аккаунте.", false); }
                else { challenge = Json.Text(result, "id"); SetStatus("Код отправлен. Действует 10 минут.", false); }
            }); }, false);
            AddPanelButton("Подтвердить", () => { var task = Safe(async () => {
                var result = await api.Call("POST", "/v1/account/verification/confirm", new { id = challenge, code = code.Password }, CancellationToken.None);
                code.Clear(); SetStatus(Json.Flag(result, "verified") ? "Почта подтверждена. Остаток Welcome — в аккаунте." : "Код неверен или истёк.", !Json.Flag(result, "verified"));
            }); }, true);
        }
        private async Task BuyResource(string sku, string title) {
            if (busy || paymentBusy || !api.Account.SignedIn) return;
            if (MessageBox.Show(title + "\nОплата откроется в браузере. Автоматических списаний нет. Смена тарифа начнётся после текущего оплаченного периода. Докупка действует 90 дней.", "Подписка", MessageBoxButton.OKCancel) != MessageBoxResult.OK) return;
            paymentBusy = true;
            try { await Safe(async () => {
                string owner = api.Account.Email;
                string key = PaymentKeys.LoadOrCreate(store.Root, owner, sku);
                var result = await api.Call("POST", "/v1/billing/checkout", new { sku = sku, idempotency_key = key }, CancellationToken.None);
                if (owner != api.Account.Email) throw new InvalidOperationException("Аккаунт изменился. Оплата остановлена.");
                string state = Json.Text(result, "state");
                if (state == "applied" || state == "test_succeeded" || state == "refunded") { PaymentKeys.Complete(store.Root, owner, sku, key); throw new InvalidOperationException("Этот платёж уже завершён. Обновите баланс; новая покупка требует отдельного действия."); }
                Uri uri;
                if (!Uri.TryCreate(Json.Text(result, "confirmation_url"), UriKind.Absolute, out uri) || uri.Scheme != "https" || uri.UserInfo.Length != 0 || uri.Port != 443 || !(uri.Host == "yoomoney.ru" || uri.Host.EndsWith(".yoomoney.ru", StringComparison.OrdinalIgnoreCase) || uri.Host == "yookassa.ru" || uri.Host.EndsWith(".yookassa.ru", StringComparison.OrdinalIgnoreCase))) throw new InvalidOperationException("Неподдержанная страница оплаты.");
                Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
                SetStatus("Баланс обновится после подтверждения оплаты", false);
            }); } finally { paymentBusy = false; }
        }
    }
}
