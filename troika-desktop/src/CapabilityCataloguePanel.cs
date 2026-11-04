using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private List<Dictionary<string, object>> catalogueItems;
        private int catalogueTab;
        private bool catalogueSaving;
        private async Task LoadCapabilityCatalogue() {
            int revision = panelRevision;
            if (!api.Account.SignedIn) {
                panelContent.Children.Clear();
                panelContent.Children.Add(Label("Войдите, чтобы управлять возможностями аккаунта.", 14, muted));
                AddPanelButton("Войти", () => OpenPanel("Аккаунт"), true); SurfaceGroup(0, "Возможности вашего аккаунта", "Плагины, навыки и инструменты", "spark");
                return;
            }
            try {
                var items = await new CapabilityCatalogueService(api).Load(CancellationToken.None);
                if (revision != panelRevision || closed) return;
                catalogueItems = items;
                RenderCapabilityCatalogue();
            } catch (Exception error) {
                if (revision != panelRevision || closed) return;
                panelContent.Children.Clear();
                var outdated = error as ApiException;
                panelContent.Children.Add(Label(outdated != null && outdated.Status == 404
                    ? "Каталог возможностей пока недоступен. Попробуйте позже."
                    : "Не удалось загрузить возможности. Проверьте соединение и повторите.", 14, muted));
                AddPanelButton("Повторить", () => OpenPanel("Возможности"), false);
                throw;
            }
        }
        private void RenderCapabilityCatalogue() {
            panelContent.Children.Clear();
            panelContent.Children.Add(Label("Тройка сама выбирает нужные возможности для задачи.", 15, text)); Gap();
            panelContent.Children.Add(Label("Общие настройки аккаунта. Изменения действуют для следующих действий и не удаляют данные.", 12, muted)); Gap();
            var tabs = new WrapPanel();
            var names = new[] { "Плагины", "Навыки", "Инструменты" };
            for (int index = 0; index < names.Length; index++) {
                int selected = index;
                var tab = Button(names[index], () => { catalogueTab = selected; RenderCapabilityCatalogue(); }, index == catalogueTab);
                tab.Margin = new Thickness(0, 0, 6, 7); tab.IsEnabled = !catalogueSaving; tabs.Children.Add(tab);
            }
            panelContent.Children.Add(tabs); Gap();
            if (catalogueItems.Count == 0) panelContent.Children.Add(Label("В этом аккаунте пока нет доступных возможностей.", 13, muted));
            foreach (var item in catalogueItems) {
                int itemCard = panelContent.Children.Count;
                bool enabled = Json.Flag(item, "enabled"), available = Json.Flag(item, "available");
                if (catalogueTab == 0) {
                    panelContent.Children.Add(Label(Json.Text(item, "description"), 12, muted));
                    var toggle = new CheckBox { Content = available ? "Подключено" : "Пока недоступно", IsChecked = enabled,
                        IsEnabled = available && !catalogueSaving, Foreground = text, FontSize = 13, Margin = new Thickness(0, 8, 0, 5) };
                    toggle.Click += async delegate { bool next = toggle.IsChecked == true; toggle.IsChecked = enabled; await SaveCapabilityPreference(Json.Text(item, "id"), next); };
                    panelContent.Children.Add(toggle);
                } else {
                    panelContent.Children.Add(Label(!enabled ? "Отключено в аккаунте" : available ? "Подключено" : "Пока недоступно", 11, muted));
                    foreach (var row in Json.Rows(item, catalogueTab == 1 ? "skills" : "tools")) {
                        var title = Json.Text(row, catalogueTab == 1 ? "description" : "title");
                        if (catalogueTab == 2 && !Json.Flag(row, "available")) title += " · недоступно";
                        panelContent.Children.Add(Label(title, 13, muted));
                    }
                }
                SurfaceGroup(itemCard, Json.Text(item, "title"), "", "spark");
            }
            int actions = panelContent.Children.Count;
            AddPanelButton("Обновить", () => OpenPanel("Возможности"), false);
            AddPanelButton("Готово", ClosePanel, false);
            CompactActions(actions);
        }
        private async Task SaveCapabilityPreference(string id, bool enabled) {
            if (catalogueSaving) return;
            int revision = panelRevision;
            catalogueSaving = true; RenderCapabilityCatalogue();
            await Safe(async () => {
                var items = await new CapabilityCatalogueService(api).SetEnabled(id, enabled, CancellationToken.None);
                if (revision == panelRevision && !closed) catalogueItems = items;
            });
            catalogueSaving = false;
            if (revision == panelRevision && !closed) RenderCapabilityCatalogue();
        }
    }
}
