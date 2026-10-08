using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private readonly DispatcherTimer reminderTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(30) };
        private bool pollingReminders;
        private void StartReminders() {
            if (preview) return;
            reminderTimer.Tick += async delegate {
                if (pollingReminders || !api.Account.SignedIn || closed) return;
                pollingReminders = true;
                await Safe(PollReminders); pollingReminders = false;
            }; reminderTimer.Start();
        }
        private async Task PollReminders() {
            var owner = api.Account.Email;
            var inbox = await api.Get("/v1/assistant/inbox?unread_only=true", CancellationToken.None);
            var settings = await api.Get("/v1/notification-preferences", CancellationToken.None);
            if (api.Account.Email != owner || !api.Account.SignedIn || closed) return;
            if (Json.Flag(settings, "quiet_hours_enabled")) {
                // The server handles the account's IANA zone and quiet hours before inbox delivery.
                // Already delivered rows must not be announced during a newly enabled quiet period.
                TimeZoneInfo zone;
                try { zone = TimeZoneInfo.FindSystemTimeZoneById(Json.Text(settings, "timezone") == "Europe/Moscow" ? "Russian Standard Time" : Json.Text(settings, "timezone") == "UTC" ? "UTC" : Json.Text(settings, "timezone")); }
                catch { return; }
                var clock = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, zone).ToString("HH:mm"); var start = Json.Text(settings, "quiet_start"); var end = Json.Text(settings, "quiet_end");
                bool quiet = string.CompareOrdinal(start, end) < 0 ? string.CompareOrdinal(clock, start) >= 0 && string.CompareOrdinal(clock, end) < 0 : string.CompareOrdinal(clock, start) >= 0 || string.CompareOrdinal(clock, end) < 0;
                if (quiet) return;
            }
            var receiptPath = Path.Combine(store.Root, "reminder-receipts-" + LocalStore.Hash(Encoding.UTF8.GetBytes(owner.ToLowerInvariant())) + ".json");
            var seen = new HashSet<string>(); try { var saved = Json.Parse(File.ReadAllText(receiptPath)); foreach (var row in Json.Rows(saved, "seen")) seen.Add(Json.Text(row, "id")); } catch { }
            foreach (var message in Json.Rows(inbox, "messages")) {
                var kind = Json.Text(message, "kind");
                if (kind == "reminder" && !Json.Flag(settings, "reminders_enabled") || kind == "proactive" && !Json.Flag(settings, "proactive_enabled")) continue;
                var id = Json.Text(message, "id"); if (id.Length == 0 || !seen.Add(id)) continue;
                LocalStore.WriteAtomic(receiptPath, Encoding.UTF8.GetBytes(Json.Encode(new { seen = seen.Select(value => new { id = value }).ToArray() })));
                var title = Json.Text(message, "title"); SetStatus("Напоминание: " + title, false); AddMessage("assistant", title + "\n" + Json.Text(message, "body"));
                var done = Button("Прочитано", () => { var task = Safe(async () => { await api.Call("POST", "/v1/assistant/inbox/" + Uri.EscapeDataString(id) + "/read", null, CancellationToken.None); }); }, false); done.HorizontalAlignment = HorizontalAlignment.Left; transcript.Children.Add(done);
                System.Media.SystemSounds.Asterisk.Play();
            }
        }
        private async Task ShowNotifications() {
            await Safe(async () => {
                var value = await api.Get("/v1/notification-preferences", CancellationToken.None); panelContent.Children.Clear(); panelContent.Children.Add(Label("Напоминания и тихие часы", 18, text)); Gap();
                var reminders = new CheckBox { Content = "Напоминания", IsChecked = Json.Flag(value, "reminders_enabled"), Foreground = text, Margin = new Thickness(0, 7, 0, 7) };
                var proactive = new CheckBox { Content = "Предложения Тройки", IsChecked = Json.Flag(value, "proactive_enabled"), Foreground = text, Margin = new Thickness(0, 7, 0, 7) };
                var quiet = new CheckBox { Content = "Тихие часы", IsChecked = Json.Flag(value, "quiet_hours_enabled"), Foreground = text, Margin = new Thickness(0, 7, 0, 7) };
                panelContent.Children.Add(reminders); panelContent.Children.Add(proactive); panelContent.Children.Add(quiet); Gap();
                panelContent.Children.Add(Label("Часовой пояс IANA", 12, muted)); var zone = Field("Часовой пояс", false); zone.Text = Json.Text(value, "timezone"); panelContent.Children.Add(zone);
                panelContent.Children.Add(Label("Не беспокоить с / до", 12, muted)); var start = Field("Начало тихих часов", false); start.Text = Json.Text(value, "quiet_start"); var end = Field("Конец тихих часов", false); end.Text = Json.Text(value, "quiet_end"); panelContent.Children.Add(start); panelContent.Children.Add(end);
                AddPanelButton("Сохранить", () => { var task = Safe(async () => { await api.Call("PUT", "/v1/notification-preferences", new { reminders_enabled = reminders.IsChecked == true, proactive_enabled = proactive.IsChecked == true, quiet_hours_enabled = quiet.IsChecked == true, timezone = zone.Text.Trim(), quiet_start = start.Text.Trim(), quiet_end = end.Text.Trim() }, CancellationToken.None); SetStatus("Настройки напоминаний сохранены", false); await ShowNotifications(); }); }, true);
                Gap(); panelContent.Children.Add(Label("В новом клиенте напоминания появляются, пока приложение открыто или свёрнуто. Доставка после полного закрытия ещё не реализована. Для остальных часовых поясов настройте IANA-зону на телефоне; при включённых тихих часах неподдержанная Windows зона блокирует звук.", 11, muted));
            });
        }
    }
}
