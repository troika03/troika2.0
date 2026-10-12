using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using Troika.Desktop;

public static class DesktopAppearanceTests {
    private static object Field(MainWindow window, string name) { return typeof(MainWindow).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(window); }
    private static object Call(MainWindow window, string name, params object[] args) { return typeof(MainWindow).GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(window, args); }
    private static void Assert(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
    [STAThread] public static int Main() {
        int exit = 1;
        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var window = new MainWindow(true) { Width = 780, Height = 540, WindowStartupLocation = WindowStartupLocation.Manual, Left = -10000, Top = -10000 };
        window.Loaded += delegate {
            window.Dispatcher.BeginInvoke(new Action(async delegate {
                try {
                    window.UpdateLayout();
                    var navigation = (Dictionary<string, Button>)Field(window, "navigation");
                    var profile = navigation["Аккаунт"];
                    var point = profile.TranslatePoint(new Point(0, 0), window);
                    Assert(profile.IsVisible && point.Y >= 0 && point.Y + profile.ActualHeight <= window.ActualHeight, "Profile is clipped at the minimum window size.");
                    await (Task)Call(window, "OpenPanelTask", "Дела");
                    Assert(((Border)Field(window, "sidebar")).IsVisible, "Opening a destination hides navigation.");
                    navigation[""].RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Assert(((Grid)Field(window, "center")).Visibility == Visibility.Visible, "Home destination does not restore the assistant.");
                    Console.WriteLine("PASS navigation and profile remain reachable at minimum size");

                    ((TextBox)Field(window, "composer")).Text = "Несохранённый черновик";
                    var answer = (TextBlock)Call(window, "AddMessage", "assistant", "Результат для проверки.");
                    typeof(MainWindow).GetField("light", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, true);
                    Call(window, "RebuildAppearance");
                    Assert(((TextBox)Field(window, "composer")).Text == "Несохранённый черновик" && answer.Text == "Результат для проверки.", "Appearance change loses conversation or draft.");
                    Call(window, "ClosePanel");
                    Assert(((ScrollViewer)Field(window, "conversationScroll")).Visibility == Visibility.Visible, "Appearance change hides the saved conversation.");
                    Console.WriteLine("PASS changing appearance preserves conversation and unsent draft");

                    var approval = new TaskCompletionSource<string>();
                    typeof(MainWindow).GetField("pendingApproval", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, approval);
                    await (Task)Call(window, "OpenPanelTask", "Подтверждение");
                    await (Task)Call(window, "OpenPanelTask", "Файлы");
                    Assert((string)Field(window, "openPanel") == "Подтверждение", "Navigation bypasses an outstanding approval.");
                    Call(window, "ClosePanel");
                    Assert(approval.Task.IsCompleted && approval.Task.Result == "deny", "Closing approval does not deny the action.");
                    Console.WriteLine("PASS navigation preserves approval and closing it denies the action");
                    exit = 0; Console.WriteLine("3 desktop appearance checks passed.");
                } catch (Exception error) { Console.Error.WriteLine(error); }
                finally { window.Close(); app.Shutdown(exit); }
            }));
        };
        window.Show(); app.Run(); return exit;
    }
}
