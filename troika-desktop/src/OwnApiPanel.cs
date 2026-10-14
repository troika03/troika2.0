using System;
using System.Windows;
using System.Windows.Controls;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private void ShowOwnApi() {
            panelContent.Children.Clear(); panelTitle.Text = "Свой API-ключ";
            panelContent.Children.Add(Label("Личная модель не расходует токены подписки. Счета модели оплачиваются провайдеру; голос сервиса учитывается отдельно. Ключ защищён средствами Windows. При ошибке на ключ Тройки не переключаемся.", 13, muted));
            var provider = new ComboBox { ItemsSource = new[] { "openrouter", "openai" }, SelectedIndex = 0, Margin = new Thickness(0, 8, 0, 8) };
            panelContent.Children.Add(provider);
            var model = Field("ID модели", false); panelContent.Children.Add(model);
            var key = new PasswordBox { Margin = new Thickness(0, 8, 0, 8) }; panelContent.Children.Add(Label("Личный API-ключ", 12, muted)); panelContent.Children.Add(key);
            AddPanelButton("Подключить свой ключ", () => {
                try { api.PersonalProviders.Save(api.Account.Email, provider.SelectedItem.ToString(), model.Text.Trim(), key.Password.Trim()); key.Clear(); status.Text = "Личный API подключён. Модель не расходует токены подписки."; }
                catch (Exception) { status.Text = "Проверьте поля личного API."; }
            }, false);
            AddPanelButton("Использовать ключ Тройки", () => { api.PersonalProviders.Disable(api.Account.Email); status.Text = "Используется ключ Тройки. Модель расходует токены подписки."; }, false);
        }
    }
}
