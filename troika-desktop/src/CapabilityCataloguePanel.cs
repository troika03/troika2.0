using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private CatalogueSnapshot catalogue;
        private int catalogueTab;
        private int catalogueFilter;
        private string catalogueQuery = "";
        private bool catalogueSaving;
        private StackPanel catalogueList;
        private static readonly string[] CatalogueTabs = { "Скиллы", "MCP", "Инструменты" };
        private static readonly string[] CatalogueFilters = { "Все", "Подключено", "Можно подключить" };

        private async Task LoadCapabilityCatalogue() {
            int revision = panelRevision;
            if (!api.Account.SignedIn) {
                panelContent.Children.Clear();
                panelContent.Children.Add(Label("Войдите, чтобы управлять возможностями аккаунта.", 14, muted));
                AddPanelButton("Войти", () => OpenPanel("Аккаунт"), true); SurfaceGroup(0, "Возможности вашего аккаунта", "", "spark");
                return;
            }
            try {
                var snapshot = await new CapabilityCatalogueService(api).LoadCatalogue(CancellationToken.None);
                if (revision != panelRevision || closed) return;
                catalogue = snapshot;
                RenderCapabilityCatalogue();
            } catch (Exception) {
                if (revision != panelRevision || closed) return;
                panelContent.Children.Clear();
                panelContent.Children.Add(Label("Не удалось загрузить возможности. Проверьте соединение и повторите.", 14, muted));
                AddPanelButton("Повторить", () => OpenPanel("Возможности"), false);
                throw;
            }
        }

        private void RenderCapabilityCatalogue() {
            panelContent.Children.Clear();
            var tabs = new WrapPanel();
            for (int index = 0; index < CatalogueTabs.Length; index++) {
                int selected = index;
                var source = index == 0 ? catalogue.Skills : index == 1 ? catalogue.Mcp : null;
                int connected = source == null ? 0 : source.Count(item => Json.Flag(item, "connected"));
                var tab = Button(CatalogueTabs[index] + (connected > 0 ? " · " + connected : ""), () => {
                    catalogueTab = selected; catalogueFilter = 0; catalogueQuery = ""; RenderCapabilityCatalogue();
                }, index == catalogueTab);
                AccessibleName(tab, CatalogueTabs[index]);
                tab.Margin = new Thickness(0, 0, 6, 7); tab.IsEnabled = !catalogueSaving; tabs.Children.Add(tab);
            }
            panelContent.Children.Add(tabs); Gap();
            if (catalogueTab == 2) { RenderCatalogueTools(); }
            else {
                var items = catalogueTab == 0 ? catalogue.Skills : catalogue.Mcp;
                if (items == null) {
                    panelContent.Children.Add(Label("Обновите сервер Тройки, чтобы увидеть этот каталог.", 13, muted));
                } else {
                    int connectable = items.Count(item => Json.Flag(item, "connectable"));
                    panelContent.Children.Add(Label((catalogueTab == 0 ? "Навыков: " : "Серверов MCP: ") + items.Count + ", для облака: " + connectable, 12, muted));
                    var search = Field(catalogueTab == 0 ? "Найти навык" : "Найти сервер MCP", false);
                    search.Text = catalogueQuery; search.Margin = new Thickness(0, 8, 0, 8);
                    search.TextChanged += delegate { catalogueQuery = search.Text; RenderCatalogueEntries(); };
                    panelContent.Children.Add(Label(catalogueTab == 0 ? "Поиск навыка" : "Поиск сервера MCP", 12, muted));
                    panelContent.Children.Add(search);
                    var filters = new WrapPanel();
                    for (int index = 0; index < CatalogueFilters.Length; index++) {
                        int selected = index;
                        var filter = Button(CatalogueFilters[index], () => { catalogueFilter = selected; RenderCapabilityCatalogue(); }, index == catalogueFilter);
                        filter.Margin = new Thickness(0, 0, 6, 7); filter.MinHeight = 36; filter.Padding = new Thickness(12, 4, 12, 4); filter.FontSize = 12;
                        filters.Children.Add(filter);
                    }
                    panelContent.Children.Add(filters);
                    if (catalogueTab == 1 && connectable == 0)
                        panelContent.Children.Add(Label("Серверы MCP пока нельзя подключить к облаку: им нужны запуск программ или вход в сервис. Причина указана у каждого сервера.", 12, muted));
                    else if (catalogueTab == 1)
                        panelContent.Children.Add(Label("Публичные серверы работают без входа и только читают. Сервисы с аккаунтом подключаются входом или токеном; изменения в них Тройка делает только после вашего подтверждения.", 12, muted));
                    Gap();
                    catalogueList = new StackPanel(); panelContent.Children.Add(catalogueList);
                    RenderCatalogueEntries();
                }
            }
            int actions = panelContent.Children.Count;
            AddPanelButton("Обновить", () => OpenPanel("Возможности"), false);
            AddPanelButton("Готово", ClosePanel, false);
            CompactActions(actions);
        }

        private void RenderCatalogueEntries() {
            catalogueList.Children.Clear();
            var items = catalogueTab == 0 ? catalogue.Skills : catalogue.Mcp;
            var query = catalogueQuery.Trim().ToLowerInvariant();
            var visible = items.Where(item => {
                bool connected = Json.Flag(item, "connected"), connectable = Json.Flag(item, "connectable");
                if (catalogueFilter == 1 && !connected) return false;
                if (catalogueFilter == 2 && (!connectable || connected)) return false;
                if (query.Length == 0) return true;
                return (Json.Text(item, "title") + " " + Json.Text(item, "description") + " " + Json.Text(item, "category_title") + " " + Json.Text(item, "id")).ToLowerInvariant().Contains(query);
            }).ToList();
            if (visible.Count == 0) catalogueList.Children.Add(Label("Ничего не найдено.", 13, muted));
            foreach (var item in visible) catalogueList.Children.Add(CatalogueCard(item));
        }

        private Border CatalogueCard(Dictionary<string, object> item) {
            bool connected = Json.Flag(item, "connected"), connectable = Json.Flag(item, "connectable");
            var content = new StackPanel();
            var heading = new DockPanel { LastChildFill = true };
            var tile = new Border { Width = 36, Height = 36, CornerRadius = new CornerRadius(12), Background = connected || connectable ? tint : glass, Margin = new Thickness(0, 0, 12, 0), Child = CatalogueIcon(Json.Text(item, "icon"), connected || connectable ? accent : muted) };
            DockPanel.SetDock(tile, Dock.Left); heading.Children.Add(tile);
            if (connected || !connectable) {
                var badge = CatalogueIcon(connected ? "check" : "lock", connected ? accent : muted); badge.Width = 16; badge.Height = 16; badge.Margin = new Thickness(8, 0, 0, 0);
                AutomationProperties.SetName(badge, connected ? "Подключено" : "Недоступно в облаке");
                DockPanel.SetDock(badge, Dock.Right); heading.Children.Add(badge);
            }
            var title = Label(Json.Text(item, "title"), 15, text); title.FontWeight = FontWeights.SemiBold; title.VerticalAlignment = VerticalAlignment.Center; heading.Children.Add(title);
            content.Children.Add(heading);
            var description = Json.Text(item, "description");
            if (description.Length > 0) { var line = Label(description, 13, muted); line.Margin = new Thickness(48, 4, 0, 0); content.Children.Add(line); }
            var category = Json.Text(item, "category_title"); if (category.Length == 0) category = Json.Text(item, "transport") == "remote" ? "Удалённый сервер" : Json.Text(item, "transport") == "local" ? "Локальный сервер" : "";
            var status = connected ? "Подключено" : connectable ? "Можно подключить" : "Недоступно в облаке";
            var meta = Label((category.Length > 0 ? category + " · " : "") + status, 12, connected ? accent : muted); meta.Margin = new Thickness(48, 6, 0, 0); content.Children.Add(meta);
            var reason = Json.Text(item, "reason");
            if (!connectable && reason.Length > 0) { var why = Label(reason, 12, muted); why.Margin = new Thickness(48, 4, 0, 0); content.Children.Add(why); }
            if (connected || connectable) {
                var id = Json.Text(item, "id"); var name = Json.Text(item, "title"); var connect = Json.Text(item, "connect");
                bool account = catalogueTab == 1 && (connect == "oauth" || connect == "token");
                var label = connected ? "Отключить" : account ? (connect == "oauth" ? "Войти" : "Ввести токен") : "Подключить";
                var entry = item;
                var action = Button(label, () => {
                    if (connected) { var task = SaveEntry(id, name, false); }
                    else if (account) ConnectService(entry);
                    else ConfirmEntry(id, name, Json.Text(entry, "homepage"));
                }, !connected);
                AccessibleName(action, label + " " + name);
                action.HorizontalAlignment = HorizontalAlignment.Left; action.Margin = new Thickness(48, 10, 0, 0); action.IsEnabled = !catalogueSaving;
                content.Children.Add(action);
            }
            return new Border { Background = CardSurface(), BorderBrush = glassLine, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(18), Padding = new Thickness(16), Margin = new Thickness(0, 0, 0, 10), Child = content };
        }

        // Same icon keys as the server and Android client (24×24 outline paths).
        private static System.Windows.Shapes.Path CatalogueIcon(string key, Brush tone) {
            string geometry;
            switch (key) {
                case "code": geometry = "M8,5 L2,12 8,19 M16,5 L22,12 16,19 M14,3 L10,21"; break;
                case "docs": geometry = "M4,4 L10,4 C11,4 12,5 12,6 L12,20 C12,19 11,18 10,18 L4,18 Z M20,4 L14,4 C13,4 12,5 12,6 L12,20 C12,19 13,18 14,18 L20,18 Z"; break;
                case "ai": geometry = "M9,3 L15,3 M12,3 L12,6 M5,6 L19,6 L19,18 L5,18 Z M9,11 L9,12 M15,11 L15,12 M9,15 L15,15 M2,10 L2,14 M22,10 L22,14"; break;
                case "search": geometry = "M17,10 A7,7 0 1 1 3,10 A7,7 0 1 1 17,10 M15,15 L21,21"; break;
                case "tasks": geometry = "M3,6 L5,8 8,4 M11,6 L21,6 M3,14 L5,16 8,12 M11,14 L21,14 M11,21 L21,21"; break;
                case "money": geometry = "M2,6 L22,6 L22,18 L2,18 Z M15,12 A3,3 0 1 1 9,12 A3,3 0 1 1 15,12 M5,9 L5,9.5 M19,14.5 L19,15"; break;
                case "chat": geometry = "M4,4 L20,4 L20,16 L9,16 L4,20 Z"; break;
                case "chart": geometry = "M3,3 L3,21 21,21 M7,16 L11,11 14,14 20,7"; break;
                case "design": geometry = "M12,3 A9,9 0 1 0 12,21 C14,21 14,19 13,18 C12,17 13,15 15,15 L18,15 C20,15 21,14 21,12 A9,9 0 0 0 12,3 M7.5,11 L7.5,11.5 M10,7 L10,7.5 M15,7.5 L15,8"; break;
                case "globe": geometry = "M21,12 A9,9 0 1 1 3,12 A9,9 0 1 1 21,12 M3,12 L21,12 M12,3 C8,8 8,16 12,21 C16,16 16,8 12,3"; break;
                case "files": geometry = "M3,6 L10,6 12,8 21,8 21,20 3,20 Z M3,6 L3,4 9,4 11,6"; break;
                case "computer": geometry = "M3,4 L21,4 L21,16 L3,16 Z M8,20 L16,20 M12,16 L12,20"; break;
                case "media": geometry = "M21,12 A9,9 0 1 1 3,12 A9,9 0 1 1 21,12 M10,8 L16,12 10,16 Z"; break;
                case "heart": geometry = "M12,20 L4,12 C1,9 3,4 7,4 C9,4 11,5 12,7 C13,5 15,4 17,4 C21,4 23,9 20,12 Z"; break;
                case "lock": geometry = "M5,11 L19,11 L19,21 L5,21 Z M8,11 L8,7 A4,4 0 0 1 16,7 L16,11"; break;
                case "check": geometry = "M21,12 A9,9 0 1 1 3,12 A9,9 0 1 1 21,12 M8,12 L11,15 16,9"; break;
                case "device": geometry = "M7,2 L17,2 L17,22 L7,22 Z M11,18 L13,18"; break;
                case "idea": geometry = "M9,18 L15,18 M10,21 L14,21 M12,3 A6,6 0 0 0 8,14 L8,16 L16,16 L16,14 A6,6 0 0 0 12,3"; break;
                default: geometry = "M9,3 L9,7 M15,3 L15,7 M6,7 L18,7 L18,12 A6,6 0 0 1 6,12 Z M12,18 L12,22"; break;
            }
            return new System.Windows.Shapes.Path { Data = Geometry.Parse(geometry), Stroke = tone, StrokeThickness = 1.6, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round, Width = 18, Height = 18, Stretch = Stretch.Uniform, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        }

        private static string ToolIcon(string id) {
            switch (id) {
                case "assistant": return "tasks";
                case "web": return "search";
                case "documents": return "docs";
                case "development": return "code";
                case "files": return "files";
                case "phone": return "device";
                case "images": return "design";
                case "vision": return "media";
                case "screen": return "computer";
                default: return "plug";
            }
        }

        private void RenderCatalogueTools() {
            panelContent.Children.Add(Label("Тройка сама выбирает нужный инструмент. Выключенные она не использует на всех устройствах.", 12, muted)); Gap();
            if (catalogue.Tools.Count == 0) panelContent.Children.Add(Label("В этом аккаунте пока нет доступных инструментов.", 13, muted));
            foreach (var item in catalogue.Tools) {
                int itemCard = panelContent.Children.Count;
                bool enabled = Json.Flag(item, "enabled"), available = Json.Flag(item, "available");
                panelContent.Children.Add(Label(Json.Text(item, "description"), 12, muted));
                var toggle = new CheckBox { Content = !available ? "Не настроено на сервере" : enabled ? "Включено" : "Выключено", IsChecked = available && enabled,
                    IsEnabled = available && !catalogueSaving, Foreground = text, FontSize = 13, Margin = new Thickness(0, 8, 0, 5) };
                AccessibleName(toggle, Json.Text(item, "title"));
                toggle.Click += async delegate { bool next = toggle.IsChecked == true; toggle.IsChecked = enabled; await SaveTool(Json.Text(item, "id"), next); };
                panelContent.Children.Add(toggle);
                foreach (var tool in Json.Rows(item, "tools")) {
                    var name = Json.Text(tool, "title"); if (!Json.Flag(tool, "available")) name += " · не настроено";
                    panelContent.Children.Add(Label("• " + name, 12, muted));
                }
                var card = SurfaceGroup(itemCard, Json.Text(item, "title"), "", "spark");
                var heading = (DockPanel)((StackPanel)card.Child).Children[0];
                var symbol = CatalogueIcon(ToolIcon(Json.Text(item, "id")), accent); symbol.Width = 20; symbol.Height = 20; symbol.Margin = new Thickness(0, 0, 10, 0);
                heading.Children.RemoveAt(0); DockPanel.SetDock(symbol, Dock.Left); heading.Children.Insert(0, symbol);
            }
        }

        private CancellationTokenSource serviceSignIn;

        private void ConnectService(Dictionary<string, object> item) {
            if (catalogueSaving) return;
            string id = Json.Text(item, "id"), name = Json.Text(item, "title");
            panelContent.Children.Clear();
            int actions;
            if (Json.Text(item, "connect") == "token") {
                var tokenName = Json.Text(item, "token_name");
                panelContent.Children.Add(Label("Вставьте " + (tokenName.Length == 0 ? "личный токен" : tokenName) + ". Выдайте только нужные права. Токен хранится зашифрованным на сервере Тройки; изменения в сервисе Тройка делает только после вашего подтверждения.", 13, muted)); Gap();
                var token = new PasswordBox { Background = background, Foreground = text, BorderBrush = line, Padding = new Thickness(12), Margin = new Thickness(0, 6, 0, 12) };
                AccessibleName(token, "Токен"); panelContent.Children.Add(token);
                Uri help;
                actions = panelContent.Children.Count;
                AddPanelButton("Подключить", () => { var task = SubmitServiceToken(id, name, token.Password.Trim()); }, true);
                if (Uri.TryCreate(Json.Text(item, "token_help"), UriKind.Absolute, out help) && help.Scheme == "https")
                    AddPanelButton("Где взять токен", () => LaunchUri(help.AbsoluteUri), false);
            } else {
                panelContent.Children.Add(Label("Откроется страница входа " + name + " в браузере. После входа Тройка сможет читать данные сервиса, а изменять их — только после вашего подтверждения каждого действия. Доступ хранится зашифрованным на сервере Тройки для вашего аккаунта. Отключить можно в любой момент.", 13, muted)); Gap();
                actions = panelContent.Children.Count;
                AddPanelButton("Войти", () => { var task = StartServiceSignIn(id, name); }, true);
            }
            AddPanelButton("Отмена", RenderCapabilityCatalogue, false);
            CompactActions(actions);
            SurfaceGroup(0, "Подключить «" + name + "»", "", "spark");
        }

        private async Task SubmitServiceToken(string id, string name, string token) {
            if (token.Length == 0 || token.Any(char.IsWhiteSpace)) { SetStatus("Вставьте токен без пробелов.", true); return; }
            int revision = panelRevision;
            catalogueSaving = true;
            await Safe(async () => {
                var service = new CapabilityCatalogueService(api);
                await service.ConnectService(id, token, CancellationToken.None);
                var snapshot = await service.LoadCatalogue(CancellationToken.None);
                if (revision == panelRevision && !closed) { catalogue = snapshot; SetStatus(name + ": подключено", false); }
            });
            catalogueSaving = false;
            if (revision == panelRevision && !closed) RenderCapabilityCatalogue();
        }

        private async Task StartServiceSignIn(string id, string name) {
            if (serviceSignIn != null) return;
            int revision = panelRevision;
            serviceSignIn = new CancellationTokenSource(TimeSpan.FromMinutes(10));
            var cancel = serviceSignIn;
            catalogueSaving = true;
            panelContent.Children.Clear();
            panelContent.Children.Add(Label("Завершите вход в браузере и вернитесь сюда. Подключение появится автоматически.", 13, muted));
            AddPanelButton("Отменить вход", () => cancel.Cancel(), false);
            SurfaceGroup(0, name + ": ожидаю вход", "", "spark");
            await Safe(async () => {
                var service = new CapabilityCatalogueService(api);
                var start = await service.ConnectService(id, null, cancel.Token);
                string status = Json.Text(start, "status");
                if (status == "waiting") {
                    LaunchUri(Json.Text(start, "authorization_url"));
                    while (status == "waiting") {
                        await Task.Delay(2000, cancel.Token);
                        status = await service.FlowStatus(Json.Text(start, "flow"), cancel.Token);
                    }
                }
                if (status != "connected") throw new InvalidOperationException(status == "expired" ? "Время входа истекло. Попробуйте ещё раз." : "Вход не завершён. Попробуйте ещё раз.");
                var snapshot = await service.LoadCatalogue(CancellationToken.None);
                if (revision == panelRevision && !closed) { catalogue = snapshot; SetStatus(name + ": подключено", false); }
            });
            cancel.Dispose(); serviceSignIn = null; catalogueSaving = false;
            if (revision == panelRevision && !closed) RenderCapabilityCatalogue();
        }

        private void ConfirmEntry(string id, string name, string homepage) {
            if (catalogueSaving) return;
            Uri address; var host = Uri.TryCreate(homepage, UriKind.Absolute, out address) ? address.Host : "";
            panelContent.Children.Clear();
            panelContent.Children.Add(Label(catalogueTab == 0
                ? "Тройка сможет применять инструкции этого навыка в разговорах на всех устройствах. Навык работает только с включёнными инструментами и не запускает программ. Отключить можно в любой момент."
                : "Тройка сможет искать и читать данные этого сервиса, когда это нужно для задачи. Текст запросов будет отправляться в " + (host.Length == 0 ? "сервис" : host) + ". Ваши ключи, файлы и история туда не передаются. Сервис только читает свои данные. Отключить можно в любой момент.", 13, muted)); Gap();
            int actions = panelContent.Children.Count;
            AddPanelButton("Подключить", () => { var task = SaveEntry(id, name, true); }, true);
            AddPanelButton("Отмена", RenderCapabilityCatalogue, false);
            CompactActions(actions);
            SurfaceGroup(0, "Подключить «" + name + "»?", "", "spark");
        }

        private Task SaveEntry(string id, string name, bool connected) {
            bool skill = catalogueTab == 0;
            return SaveCatalogue(token => skill
                ? new CapabilityCatalogueService(api).SetSkillConnected(id, connected, token)
                : new CapabilityCatalogueService(api).SetMcpConnected(id, connected, token), name + ": " + (connected ? "подключено" : "отключено"));
        }

        private Task SaveTool(string id, bool enabled) {
            return SaveCatalogue(token => new CapabilityCatalogueService(api).SetToolEnabled(id, enabled, token), enabled ? "Инструменты включены" : "Инструменты выключены");
        }

        private async Task SaveCatalogue(Func<CancellationToken, Task<CatalogueSnapshot>> action, string done) {
            if (catalogueSaving) return;
            int revision = panelRevision;
            catalogueSaving = true; RenderCapabilityCatalogue();
            await Safe(async () => {
                var snapshot = await action(CancellationToken.None);
                if (revision == panelRevision && !closed) { catalogue = snapshot; SetStatus(done, false); }
            });
            catalogueSaving = false;
            if (revision == panelRevision && !closed) RenderCapabilityCatalogue();
        }
    }
}
