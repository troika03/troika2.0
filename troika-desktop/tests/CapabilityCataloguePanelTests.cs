using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using Troika.Desktop;

// Renders the Скиллы / MCP / Инструменты panel with a fixed catalogue and checks
// that every entry is visible, searchable and keeps actions inside the window.
public static class CapabilityCataloguePanelTests {
    private static object Field(MainWindow window, string name) { return typeof(MainWindow).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(window); }
    private static void SetField(MainWindow window, string name, object value) { typeof(MainWindow).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, value); }
    private static object Call(MainWindow window, string name, params object[] args) { return typeof(MainWindow).GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(window, args); }
    private static void Assert(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
    private static IEnumerable<T> Descendants<T>(DependencyObject parent) where T : DependencyObject {
        for (int index = 0; index < VisualTreeHelper.GetChildrenCount(parent); index++) {
            var child = VisualTreeHelper.GetChild(parent, index); if (child is T) yield return (T)child;
            foreach (var descendant in Descendants<T>(child)) yield return descendant;
        }
    }
    private static Button Find(MainWindow window, string name) { return Descendants<Button>(window).FirstOrDefault(button => AutomationProperties.GetName(button) == name && button.IsVisible); }
    private static bool HasText(MainWindow window, string value) { return Descendants<TextBlock>(window).Any(block => block.IsVisible && block.Text == value); }

    private static CatalogueSnapshot Sample() {
        return CapabilityCatalogueService.ParseCatalogue(Json.Parse(Json.Encode(new {
            @object = "troika.extensions",
            skills = new object[] {
                new { id = "creative/humanizer", title = "Живой текст", description = "Убирает шаблонные обороты и делает текст естественным.", category_title = "Творчество", icon = "design", connectable = true, connected = true, reason = "" },
                new { id = "business-startup", title = "Бизнес и стартап", description = "Идея, рынок, запуск и рост продукта.", category_title = "Общее", icon = "idea", connectable = true, connected = false, reason = "" },
                new { id = "apple/apple-notes", title = "apple-notes", description = "Manage Apple Notes via memo CLI: create, search, edit.", category_title = "Apple", icon = "device", connectable = false, connected = false, reason = "Нужны программы или ключи, которых нет в облаке Тройки." },
            },
            mcp = new object[] {
                new { id = "deepwiki", title = "DeepWiki", description = "Документация и ответы по публичным репозиториям GitHub.", category_title = "Разработка", icon = "code", transport = "remote", homepage = "https://mcp.deepwiki.com/mcp", connectable = true, connected = false, reason = "" },
                new { id = "github", title = "GitHub", description = "Репозитории, задачи и pull request.", category_title = "Разработка", icon = "code", transport = "remote", homepage = "https://api.githubcopilot.com/mcp/", connect = "token", token_name = "Personal access token GitHub", token_help = "https://github.com/settings/personal-access-tokens", connectable = true, connected = false, reason = "" },
                new { id = "notion", title = "Notion", description = "Страницы и базы данных Notion.", category_title = "Продуктивность", icon = "tasks", transport = "remote", homepage = "https://mcp.notion.com/mcp", connect = "oauth", connectable = true, connected = false, reason = "" },
                new { id = "linear", title = "Linear", icon = "tasks", description = "Find, create, and update Linear issues, projects, and comments.", transport = "remote", connectable = false, connected = false, reason = "Нужен вход в аккаунт сервиса. Подключение сервисов к аккаунту Тройки пока не готово." },
                new { id = "n8n", title = "N8N", description = "Manage and inspect n8n workflows.", transport = "local", connectable = false, connected = false, reason = "Запускает программу на сервере — в облаке Тройки это запрещено." },
            },
            tools = new object[] {
                new { id = "web", title = "Поиск в интернете", description = "Находить информацию и источники.", enabled = true, available = true, tools = new object[] { new { id = "web_search", title = "Поиск страниц", available = true } } },
                new { id = "images", title = "Создание изображений", description = "Создавать изображения через настроенный сервис.", enabled = false, available = true, tools = new object[] { new { id = "image_generate", title = "Генерация изображения", available = true } } },
            },
        })));
    }

    private static void CheckBounds(MainWindow window) {
        window.UpdateLayout();
        foreach (var button in Descendants<Button>(window).Where(item => item.IsVisible)) {
            var point = button.TranslatePoint(new Point(0, 0), window);
            Assert(point.X >= -1 && point.X + button.ActualWidth <= window.ActualWidth + 1, "A button leaves the window horizontally: " + AutomationProperties.GetName(button));
        }
    }

    [STAThread] public static int Main(string[] args) {
        int exit = 1; string output = args.Length > 0 ? args[0] : "";
        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var window = new MainWindow(true) { Width = 960, Height = 680, ShowActivated = false, WindowStartupLocation = WindowStartupLocation.Manual, Left = -10000, Top = -10000 };
        window.Loaded += delegate {
            window.Dispatcher.BeginInvoke(new Action(async delegate {
                try {
                    foreach (var light in new[] { false, true }) {
                        foreach (var width in new[] { 780.0, 1280.0 }) {
                            await window.PreviewLayout(Path.GetTempFileName(), width, 680, light, false, "Возможности");
                            Assert(HasText(window, "Войдите, чтобы управлять возможностями аккаунта."), "Unsigned catalogue must offer sign-in.");
                            SetField(window, "catalogue", Sample()); SetField(window, "catalogueTab", 0); SetField(window, "catalogueFilter", 0); SetField(window, "catalogueQuery", "");
                            Call(window, "RenderCapabilityCatalogue"); window.UpdateLayout();
                            Assert(Find(window, "Скиллы") != null && Find(window, "MCP") != null && Find(window, "Инструменты") != null, "Catalogue tabs are missing.");
                            Assert(HasText(window, "Живой текст") && HasText(window, "apple-notes") && HasText(window, "Нужны программы или ключи, которых нет в облаке Тройки."), "Skills or unavailable reason are missing.");
                            Assert(Find(window, "Отключить Живой текст") != null && Find(window, "Подключить Бизнес и стартап") != null && Find(window, "Подключить apple-notes") == null, "Skill actions do not match connection state.");
                            CheckBounds(window);
                            string theme = light ? "light" : "dark";
                            if (output.Length > 0) window.RenderTo(Path.Combine(output, "capabilities-skills-" + theme + "-" + width + ".png"));
                            // Search narrows the list without reloading the panel.
                            var search = Descendants<TextBox>(window).First(box => AutomationProperties.GetName(box) == "Найти навык");
                            search.Text = "apple"; window.UpdateLayout();
                            Assert(!HasText(window, "Живой текст") && HasText(window, "apple-notes"), "Search does not filter skills.");
                            // Connecting asks for confirmation first.
                            search.Text = ""; window.UpdateLayout();
                            Find(window, "Подключить Бизнес и стартап").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Assert(Descendants<TextBlock>(window).Any(block => block.IsVisible && block.Text == "Подключить «Бизнес и стартап»?"), "Connecting a skill skips confirmation.");
                            Find(window, "Отмена").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Find(window, "MCP").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Assert(HasText(window, "Linear") && HasText(window, "Запускает программу на сервере — в облаке Тройки это запрещено."), "MCP entries or reasons are missing.");
                            Assert(Find(window, "Подключить DeepWiki") != null && Find(window, "Подключить Linear") == null, "MCP actions do not match the reviewed cloud list.");
                            Find(window, "Подключить DeepWiki").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Assert(Descendants<TextBlock>(window).Any(block => block.IsVisible && block.Text.Contains("mcp.deepwiki.com")), "MCP confirmation does not name the receiving host.");
                            Find(window, "Отмена").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Find(window, "Ввести токен GitHub").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Assert(Descendants<PasswordBox>(window).Any(box => box.IsVisible) && Find(window, "Где взять токен") != null, "Token sign-in must use a hidden field and link to the token page.");
                            Find(window, "Отмена").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Assert(Find(window, "Войти Notion") != null, "OAuth services must offer sign-in.");
                            Find(window, "Войти Notion").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            Assert(Descendants<TextBlock>(window).Any(block => block.IsVisible && block.Text.Contains("только после вашего подтверждения")), "OAuth confirmation must explain write approvals.");
                            Find(window, "Отмена").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            CheckBounds(window);
                            if (output.Length > 0) window.RenderTo(Path.Combine(output, "capabilities-mcp-" + theme + "-" + width + ".png"));
                            Find(window, "Инструменты").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); window.UpdateLayout();
                            var toggles = Descendants<CheckBox>(window).Where(box => box.IsVisible).ToList();
                            Assert(toggles.Count == 2 && toggles[0].IsChecked == true && toggles[1].IsChecked == false, "Tool switches do not reflect the account state.");
                            CheckBounds(window);
                            if (output.Length > 0) window.RenderTo(Path.Combine(output, "capabilities-tools-" + theme + "-" + width + ".png"));
                        }
                    }
                    exit = 0; Console.WriteLine("Capability catalogue panel checks passed: tabs, search, confirmation, MCP reasons, tool switches in two themes and widths.");
                } catch (Exception error) { Console.Error.WriteLine(error); }
                finally { window.Close(); app.Shutdown(exit); }
            }));
        };
        window.Show(); app.Run();
        return exit;
    }
}
