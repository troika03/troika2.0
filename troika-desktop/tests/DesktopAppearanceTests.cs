using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Automation;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using Troika.Desktop;

public static class DesktopAppearanceTests {
    private sealed class NavigationHandler : HttpMessageHandler {
        public Func<HttpRequestMessage, Task<HttpResponseMessage>> Route;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) { return Route(request); }
    }
    private static HttpResponseMessage Messages(string content) { return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(Json.Encode(new { messages = new[] { new { role = "assistant", content } } })) }; }
    private static object Field(MainWindow window, string name) { return typeof(MainWindow).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(window); }
    private static object Call(MainWindow window, string name, params object[] args) { return typeof(MainWindow).GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(window, args); }
    private static void Assert(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
    private static IEnumerable<T> Descendants<T>(DependencyObject parent) where T : DependencyObject {
        for (int index = 0; index < VisualTreeHelper.GetChildrenCount(parent); index++) {
            var child = VisualTreeHelper.GetChild(parent, index); if (child is T) yield return (T)child;
            foreach (var descendant in Descendants<T>(child)) yield return descendant;
        }
    }
    [STAThread] public static int Main() {
        int exit = 1;
        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var window = new MainWindow(true) { Width = 780, Height = 540, WindowStartupLocation = WindowStartupLocation.Manual, Left = -10000, Top = -10000 };
        window.Loaded += delegate {
            window.Dispatcher.BeginInvoke(new Action(async delegate {
                try {
                    window.UpdateLayout();
                    Assert(((Grid)Field(window, "hero")).Visibility == Visibility.Visible && ((ScrollViewer)Field(window, "conversationScroll")).Visibility == Visibility.Collapsed, "Opening the application must show the voice home.");
                    var navigation = (Dictionary<string, Button>)Field(window, "navigation");
                    string[] destinations = { "", "Разговоры", "Дела", "Файлы", "Разработка", "Память", "Возможности", "Аккаунт" };
                    string[] labels = { "Главная", "Разговоры", "Дела", "Файлы", "Разработка", "Память", "Возможности", "Настройки" };
                    for (int index = 0; index < destinations.Length; index++) {
                        Assert(navigation.ContainsKey(destinations[index]) && AutomationProperties.GetName(navigation[destinations[index]]) == labels[index], "A shared destination is missing or mislabeled: " + labels[index]);
                    }
                    await (Task)Call(window, "OpenPanelTask", "Разговоры");
                    window.UpdateLayout();
                    Assert((string)Field(window, "openPanel") == "Разговоры" && ((TextBlock)Field(window, "panelTitle")).Text == "Разговоры", "Conversation navigation does not open its own destination.");
                    Assert(Descendants<TextBlock>(window).Any(block => block.Text == "Войдите, чтобы открыть разговоры."), "Unsigned conversation history fails to offer the account entry.");
                    Call(window, "ClosePanel");
                    var profile = navigation["Аккаунт"];
                    var point = profile.TranslatePoint(new Point(0, 0), window);
                    Assert(profile.IsVisible && point.Y >= 0 && point.Y + profile.ActualHeight <= window.ActualHeight, "Profile is clipped at the minimum window size.");
                    await (Task)Call(window, "OpenPanelTask", "Дела");
                    Assert(((Border)Field(window, "sidebar")).IsVisible, "Opening a destination hides navigation.");
                    navigation[""].RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Assert(((Grid)Field(window, "center")).Visibility == Visibility.Visible, "Home destination does not restore the assistant.");
                    Console.WriteLine("PASS shared destinations open correctly and settings remain reachable at minimum size");

                    ((TextBox)Field(window, "composer")).Text = "Несохранённый черновик";
                    var answer = (TextBlock)Call(window, "AddMessage", "assistant", "Результат для проверки.");
                    var currentApi = (ApiClient)Field(window, "api"); currentApi.SessionId = "desktop-navigation-fixture";
                    var currentTranscript = (StackPanel)Field(window, "transcript"); int messageCount = currentTranscript.Children.Count;
                    Assert(AutomationProperties.GetHelpText(navigation["Разговоры"]) == "Текущий раздел", "An open conversation is incorrectly labeled as Home.");
                    navigation[""].RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Assert(((Grid)Field(window, "hero")).Visibility == Visibility.Visible && ((ScrollViewer)Field(window, "conversationScroll")).Visibility == Visibility.Collapsed, "Home navigation keeps the transcript visible instead of the voice home.");
                    Assert(currentTranscript.Children.Count == messageCount && answer.Text == "Результат для проверки." && ((TextBox)Field(window, "composer")).Text == "Несохранённый черновик" && currentApi.SessionId == "desktop-navigation-fixture", "Returning Home loses messages, the unsent draft or the current session.");
                    await (Task)Call(window, "OpenPanelTask", "Дела"); Call(window, "ClosePanel");
                    Assert(((Grid)Field(window, "hero")).Visibility == Visibility.Visible, "Closing a panel opened from Home unexpectedly restores the conversation.");
                    await (Task)Call(window, "OpenPanelTask", "Разговоры");
                    Descendants<Button>(window).Single(button => AutomationProperties.GetName(button) == "Продолжить разговор").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Assert(((ScrollViewer)Field(window, "conversationScroll")).Visibility == Visibility.Visible && currentTranscript.Children.Count == messageCount && ((TextBox)Field(window, "composer")).Text == "Несохранённый черновик", "Continuing a conversation reloads or loses its local content.");
                    await (Task)Call(window, "OpenPanelTask", "Дела"); Call(window, "ClosePanel");
                    Assert(((ScrollViewer)Field(window, "conversationScroll")).Visibility == Visibility.Visible && AutomationProperties.GetHelpText(navigation["Разговоры"]) == "Текущий раздел", "Closing a panel loses the conversation destination.");
                    Console.WriteLine("PASS voice Home and conversation navigation preserve messages, draft and session");
                    typeof(MainWindow).GetField("light", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, true);
                    Call(window, "RebuildAppearance");
                    Assert(((TextBox)Field(window, "composer")).Text == "Несохранённый черновик" && answer.Text == "Результат для проверки.", "Appearance change loses conversation or draft.");
                    Call(window, "ClosePanel");
                    Assert(((ScrollViewer)Field(window, "conversationScroll")).Visibility == Visibility.Visible, "Appearance change hides the saved conversation.");
                    Console.WriteLine("PASS changing appearance preserves conversation and unsent draft");

                    await (Task)Call(window, "OpenPanelTask", "Возможности"); window.UpdateLayout();
                    Assert(Descendants<TextBlock>(window).Any(block => block.Text == "Войдите, чтобы управлять возможностями аккаунта."), "Capabilities navigation opens device actions instead of the account catalogue.");
                    await (Task)Call(window, "OpenPanelTask", "Каталог возможностей");
                    Assert((string)Field(window, "openPanel") == "Возможности", "The legacy catalogue route fails to select the shared destination.");
                    await (Task)Call(window, "OpenPanelTask", "Действия на ПК");
                    foreach (double width in new[] { 780.0, 960.0 }) {
                        window.Width = width; window.UpdateLayout();
                        var cards = ((StackPanel)Field(window, "panelContent")).Children.OfType<WrapPanel>().First();
                        var first = (Button)cards.Children[0]; var second = (Button)cards.Children[1];
                        var firstPoint = first.TranslatePoint(new Point(0, 0), cards);
                        var secondPoint = second.TranslatePoint(new Point(0, 0), cards);
                        Assert(Math.Abs(firstPoint.Y - secondPoint.Y) < 1 && secondPoint.X > firstPoint.X, "Capabilities collapse to full-width rows at a supported desktop size.");
                        foreach (Button card in cards.Children) {
                            var cardPoint = card.TranslatePoint(new Point(0, 0), cards);
                            Assert(card.ActualWidth > 0 && cardPoint.X >= 0 && cardPoint.X + card.ActualWidth <= cards.ActualWidth + 1, "A capability card clips beyond the content area.");
                        }
                    }
                    var primaryCards = ((StackPanel)Field(window, "panelContent")).Children.OfType<WrapPanel>().First();
                    var document = primaryCards.Children.OfType<Button>().Single(button => AutomationProperties.GetName(button) == "Документ DOCX");
                    document.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Assert(((Grid)Field(window, "center")).Visibility == Visibility.Visible && ((TextBox)Field(window, "composer")).Text == "Создай DOCX: " && !(bool)Field(window, "busy"), "Document card fails to return an unsent request to the assistant.");
                    Console.WriteLine("PASS capability cards fit narrow and wide windows and prepare an unsent document request");

                    await (Task)Call(window, "OpenPanelTask", "Разработка"); window.UpdateLayout();
                    var request = Descendants<TextBox>(window).Single(field => AutomationProperties.GetName(field) == "Какой проект создать");
                    request.Text = "Проект с несохранённым описанием";
                    var choice = Descendants<ComboBox>(window).Single(); choice.SelectedItem = "JavaScript: тесты"; choice.IsDropDownOpen = true;
                    await window.Dispatcher.InvokeAsync(new Action(window.UpdateLayout), System.Windows.Threading.DispatcherPriority.ApplicationIdle);
                    var popup = (Popup)choice.Template.FindName("PART_Popup", choice);
                    Assert(popup != null && popup.IsOpen && popup.Child.RenderSize.Height > 0 && Convert.ToString(choice.SelectionBoxItem) == "JavaScript: тесты", "The themed selector fails: popup=" + (popup != null) + ", open=" + (popup != null && popup.IsOpen) + ", height=" + (popup == null ? 0 : popup.Child.RenderSize.Height) + ", selection=" + Convert.ToString(choice.SelectionBoxItem));
                    choice.IsDropDownOpen = false; Call(window, "RenderDevelopment"); window.UpdateLayout();
                    Assert(Descendants<TextBox>(window).Single(field => AutomationProperties.GetName(field) == "Какой проект создать").Text == "Проект с несохранённым описанием", "Grouping the development form loses its unsent description.");
                    Console.WriteLine("PASS themed selector opens and development cards preserve an unsent description");

                    var taskContent = (StackPanel)Field(window, "panelContent"); taskContent.Children.Clear();
                    Call(window, "RenderTasks", Json.Parse("{\"tasks\":[{\"id\":\"sample\",\"title\":\"Существующее дело\"}]}"), Json.Parse("{\"projects\":[]}")); window.UpdateLayout();
                    var taskForm = Descendants<Expander>(window).Single(); Assert(!taskForm.IsExpanded, "Existing tasks are hidden behind an expanded creation form.");
                    taskForm.IsExpanded = true; window.UpdateLayout();
                    var taskName = Descendants<TextBox>(window).Single(field => AutomationProperties.GetName(field) == "Название задачи"); taskName.Text = "Несохранённое дело";
                    var reminderDate = Descendants<DatePicker>(window).Single(); reminderDate.SelectedDate = DateTime.Today.AddDays(2);
                    reminderDate.IsDropDownOpen = true; await window.Dispatcher.InvokeAsync(new Action(window.UpdateLayout), System.Windows.Threading.DispatcherPriority.ApplicationIdle);
                    var calendar = (Popup)reminderDate.Template.FindName("PART_Popup", reminderDate);
                    Assert(calendar != null && calendar.IsOpen && calendar.Child.RenderSize.Height > 0, "The themed reminder date cannot open its calendar.");
                    reminderDate.IsDropDownOpen = false; taskForm.IsExpanded = false; taskForm.IsExpanded = true; window.UpdateLayout();
                    Assert(taskName.Text == "Несохранённое дело" && reminderDate.SelectedDate == DateTime.Today.AddDays(2), "Collapsing the task form loses its draft or reminder date.");
                    Console.WriteLine("PASS task form preserves draft and date while calendar remains available");

                    var originalApi = (ApiClient)Field(window, "api");
                    var handler = new NavigationHandler();
                    using (var historyApi = new ApiClient(handler, "https://example.test") { Account = new AccountSession { Email = "navigation@example.test", DeviceId = "fixture-device", Token = "trk_live_fixture", RefreshToken = "trk_refresh_fixture", HomeSession = "fixture-home", ExpiresAt = 9999999999 }, SessionId = "fixture-current" }) {
                        typeof(MainWindow).GetField("api", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, historyApi);
                        try {
                            var delayed = new TaskCompletionSource<HttpResponseMessage>(); handler.Route = httpRequest => delayed.Task;
                            Call(window, "ShowHome"); var pendingHistory = (Task)Call(window, "LoadConversation", "fixture-old");
                            Call(window, "ShowHome"); delayed.SetResult(Messages("Запоздалая история")); await pendingHistory;
                            Assert(((Grid)Field(window, "hero")).Visibility == Visibility.Visible && historyApi.SessionId == "fixture-current", "A delayed history response overrides a later Home action.");
                            handler.Route = httpRequest => {
                                historyApi.Account = new AccountSession { Email = "navigation@example.test", DeviceId = "fixture-device", Token = "trk_live_refreshed_fixture", RefreshToken = "trk_refresh_refreshed_fixture", HomeSession = "fixture-home", ExpiresAt = 9999999999 };
                                return Task.FromResult(Messages("Сохранённый разговор"));
                            };
                            await (Task)Call(window, "LoadConversation", "fixture-restored");
                            window.UpdateLayout();
                            Assert(historyApi.SessionId == "fixture-restored" && ((ScrollViewer)Field(window, "conversationScroll")).Visibility == Visibility.Visible && Descendants<TextBlock>(window).Any(block => block.Text == "Сохранённый разговор"), "Refreshing a session for the same account incorrectly hides the selected conversation: session=" + historyApi.SessionId + ", status=" + ((TextBlock)Field(window, "status")).Text);
                            delayed = new TaskCompletionSource<HttpResponseMessage>(); handler.Route = httpRequest => delayed.Task;
                            pendingHistory = (Task)Call(window, "LoadConversation", "fixture-other");
                            historyApi.Account = new AccountSession { Email = "other@example.test", DeviceId = "other-device", Token = "trk_live_other_fixture", RefreshToken = "trk_refresh_other_fixture", HomeSession = "other-home", ExpiresAt = 9999999999 };
                            delayed.SetResult(Messages("Чужая история")); await pendingHistory;
                            Assert(historyApi.SessionId == "fixture-restored" && !Descendants<TextBlock>(window).Any(block => block.Text == "Чужая история"), "A history response crosses an account change.");
                        } finally { typeof(MainWindow).GetField("api", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, originalApi); }
                    }
                    Console.WriteLine("PASS delayed history respects Home, account changes and same-account refresh");

                    var approval = new TaskCompletionSource<string>();
                    typeof(MainWindow).GetField("pendingApproval", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, approval);
                    await (Task)Call(window, "OpenPanelTask", "Подтверждение");
                    await (Task)Call(window, "OpenPanelTask", "Файлы");
                    Assert((string)Field(window, "openPanel") == "Подтверждение", "Navigation bypasses an outstanding approval.");
                    Call(window, "ClosePanel");
                    Assert(approval.Task.IsCompleted && approval.Task.Result == "deny", "Closing approval does not deny the action.");
                    Console.WriteLine("PASS navigation preserves approval and closing it denies the action");
                    exit = 0; Console.WriteLine("8 desktop appearance checks passed.");
                } catch (Exception error) { Console.Error.WriteLine(error); }
                finally { window.Close(); app.Shutdown(exit); }
            }));
        };
        window.Show(); app.Run(); return exit;
    }
}
