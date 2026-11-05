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
using System.Windows.Media.Imaging;
using Troika.Desktop;

static class VoiceIdentityUiTests {
    private static object Field(MainWindow window, string name) { return typeof(MainWindow).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(window); }
    private static void Set(MainWindow window, string name, object value) { typeof(MainWindow).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(window, value); }
    private static object Call(MainWindow window, string name, params object[] values) { return typeof(MainWindow).GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(window, values); }
    private static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
    private static IEnumerable<T> Children<T>(DependencyObject root) where T : DependencyObject {
        for (int index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++) { var child = VisualTreeHelper.GetChild(root, index); if (child is T) yield return (T)child; foreach (var descendant in Children<T>(child)) yield return descendant; }
    }
    private static Button Button(MainWindow window, string title) { return Children<Button>(window).Single(button => AutomationProperties.GetName(button) == title); }
    private static void Click(MainWindow window, string title) { Button(window, title).RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Button.ClickEvent)); window.UpdateLayout(); }
    private static void Save(MainWindow window, string path) {
        window.UpdateLayout(); var image = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32); image.Render(window);
        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(image)); using (var stream = File.Create(path)) encoder.Save(stream);
    }
    [STAThread] public static int Main() {
        int result = 1; var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var window = new MainWindow(true) { Width = 780, Height = 540, ShowActivated = false, WindowStartupLocation = WindowStartupLocation.Manual, Left = -10000, Top = -10000 };
        window.Loaded += delegate { window.Dispatcher.BeginInvoke(new Action(async delegate {
            try {
                var api = (ApiClient)Field(window, "api"); api.Account = new AccountSession { Email = "voice-ui@example.test", Token = "trk_live_fixture", RefreshToken = "trk_refresh_fixture", HomeSession = "home_fixture", ExpiresAt = 9999999999 };
                var store = (VoiceIdentityStore)Field(window, "voiceIdentities"); var recorder = (VoiceRecorder)Field(window, "recorder");
                string output = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "voice-identity-renders"); Directory.CreateDirectory(output);
                foreach (bool light in new[] { false, true }) {
                    Set(window, "light", light); Call(window, "Build"); await (Task)Call(window, "OpenPanelTask", "Мой голос"); window.UpdateLayout();
                    Assert(!recorder.Recording && !store.Load(api.Account.Email).Exists, "Opening settings activated capture or wrote a profile");
                    Assert(Children<TextBlock>(window).Any(text => text.Text == "Образец только на этом ПК."), "Local storage label is missing");
                    Save(window, Path.Combine(output, "my-voice-" + (light ? "light" : "dark") + "-780.png"));
                    Click(window, "Зарегистрировать мой голос");
                    Assert((bool)Field(window, "voiceEnrollment") && !recorder.Recording, "Enrollment screen started microphone without record action");
                    Assert(Children<TextBlock>(window).Any(text => text.Text == "Образец 1 из 3"), "Enrollment prompt is missing");
                    Save(window, Path.Combine(output, "enrollment-" + (light ? "light" : "dark") + "-780.png"));
                    int epoch = (int)Field(window, "voiceIdentityEpoch"); Call(window, "ClosePanel");
                    Assert(!(bool)Field(window, "voiceEnrollment") && (int)Field(window, "voiceIdentityEpoch") > epoch && !store.Load(api.Account.Email).Exists, "Leaving enrollment retained an active or persisted partial profile");
                }
                Console.WriteLine("PASS voice enrollment screens render in both themes; opening settings and enrollment do not start microphone; leaving cancels partial registration");
                double[] vector = new double[128]; vector[0] = 1; var signature = new VoiceSignature(vector, 450);
                store.Enroll(api.Account.Email, new[] { signature, signature, signature });
                await (Task)Call(window, "OpenPanelTask", "Мой голос"); window.UpdateLayout();
                var check = Children<CheckBox>(window).Single(item => Convert.ToString(item.Content) == "Отзываться только на мой голос");
                Assert(check.IsChecked == false && !store.Load(api.Account.Email).Enabled, "Enrollment auto-enabled filtering");
                check.IsChecked = true; check.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent));
                Assert(store.Load(api.Account.Email).Enabled, "Explicit opt-in did not enable filtering");
                window.UpdateLayout(); Assert(Children<TextBlock>(window).Any(text => text.Text.Contains("не меньше 4 секунд")), "Enabled filter hides minimum phrase duration");
                Click(window, "Удалить образец голоса"); Assert(!store.Load(api.Account.Email).Exists && !store.Load(api.Account.Email).Enabled, "Deleting voice kept biometric data or filter enabled");
                Console.WriteLine("PASS explicit switch enables filtering and delete removes account-scoped profile");
                result = 0;
            } catch (Exception error) { Console.Error.WriteLine(error); }
            finally { window.Close(); app.Shutdown(result); }
        })); };
        window.Show(); app.Run(); return result;
    }
}
