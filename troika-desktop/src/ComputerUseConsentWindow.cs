using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Net.Http;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;

namespace Troika.Desktop {
    internal sealed class ComputerUseConsentWindow : Window {
        private sealed class Consent {
            internal readonly string RunId;
            internal readonly string GrantId;
            public string Label { get { return "Запрос " + RunId.Substring(4, 8); } }

            internal Consent(string runId, string grantId) { RunId = runId; GrantId = grantId; }

            internal string Path(string operation) {
                return "/v1/runs/" + RunId + "/computer-dry-run/" + operation;
            }
        }

        private readonly ApiClient client;
        private readonly TextBlock status;
        private Consent active;
        private bool busy, stopping, closing, allowClose;
        private Task stopTask;
        internal Task Operation { get; private set; }
        internal readonly ListBox Requests;
        internal readonly Button RefreshButton, AllowButton, DenyButton, StopButton;

        internal static ApiClient Connect(string address, string token, HttpMessageHandler handler = null) {
            var origin = ComputerUseAgent.LoopbackOrigin(address);
            if (token == null || !Regex.IsMatch(token, @"\Atrk_live_[A-Za-z0-9_-]{43}\z"))
                throw new ArgumentException("Нужен токен тестового устройства Windows.");
            return new ApiClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false },
                origin.AbsoluteUri) { Account = new AccountSession { Token = token } };
        }

        internal ComputerUseConsentWindow(ApiClient client) {
            this.client = client;
            Title = "Тройка — согласие на симуляцию";
            Width = 540;
            MinWidth = 400;
            SizeToContent = SizeToContent.Height;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            FontFamily = BrandAssets.Font;
            FontSize = 14;
            SetResourceReference(BackgroundProperty, SystemColors.WindowBrushKey);
            SetResourceReference(ForegroundProperty, SystemColors.WindowTextBrushKey);

            var body = new StackPanel { Margin = new Thickness(24) };
            var title = Paragraph("Разрешение на пробное нажатие");
            title.FontSize = 22;
            title.FontWeight = FontWeights.Medium;
            body.Children.Add(title);
            body.Children.Add(Paragraph("Запрос даёт Тройке до двух минут на осмотр и нажатие в синтетическом окне."));
            Requests = new ListBox { DisplayMemberPath = "Label", MinHeight = 48, MaxHeight = 150,
                Margin = new Thickness(0, 0, 0, 12) };
            AutomationProperties.SetName(Requests, "Ожидающие запросы");
            Requests.SelectionChanged += (sender, args) => RefreshButtons();
            body.Children.Add(Requests);
            var actions = new WrapPanel();
            AllowButton = ActionButton("Разрешить", () => Operation = DecideAsync(true));
            DenyButton = ActionButton("Отклонить", () => Operation = DecideAsync(false));
            StopButton = ActionButton("Остановить (Esc)", () => Operation = StopAsync());
            RefreshButton = ActionButton("Обновить запросы", () => Operation = RefreshAsync());
            foreach (var button in new[] { AllowButton, DenyButton, StopButton, RefreshButton })
                actions.Children.Add(button);
            body.Children.Add(actions);
            status = Paragraph("Загружаю запросы.");
            body.Children.Add(status);
            Content = body;
            Loaded += (sender, args) => Operation = RefreshAsync();
            Closing += OnClosing;
            PreviewKeyDown += (sender, args) => {
                if (args.Key != Key.Escape || active == null) return;
                args.Handled = true;
                Operation = StopAsync();
            };
            RefreshButtons();
        }

        private static TextBlock Paragraph(string text) {
            return new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, LineHeight = 22,
                Margin = new Thickness(0, 0, 0, 12) };
        }

        private static Button ActionButton(string text, Action invoke) {
            var button = new Button { Content = text, MinHeight = 36, Margin = new Thickness(0, 0, 8, 8),
                Padding = new Thickness(10, 4, 10, 4) };
            button.Click += (sender, args) => invoke();
            return button;
        }

        private void RefreshButtons() {
            bool canChoose = !closing && !busy && active == null;
            Requests.IsEnabled = canChoose;
            RefreshButton.IsEnabled = canChoose;
            AllowButton.IsEnabled = canChoose && Requests.SelectedItem is Consent;
            DenyButton.IsEnabled = AllowButton.IsEnabled;
            StopButton.IsEnabled = !closing && !stopping && active != null;
        }

        private async Task RefreshAsync() {
            if (busy || closing || active != null) return;
            busy = true;
            Requests.Items.Clear();
            RefreshButtons();
            var response = await SendAsync("GET", "/v1/computer-dry-run/requests", null);
            if (!closing && response != null && object.Equals(Json.Get(response, "version"), 1)) {
                foreach (var item in Json.Rows(response, "requests").Take(64)) {
                    string run = Json.Text(item, "run_id");
                    string grant = Json.Text(item, "grant_id");
                    if (Json.Text(item, "mode") == "dry_run" && Json.Text(item, "status") == "pending"
                            && Json.Text(item, "platform") == "windows" && Regex.IsMatch(run, @"\Arun_[a-f0-9]{32}\z")
                            && Regex.IsMatch(grant, @"\A[a-f0-9]{32}\z"))
                        Requests.Items.Add(new Consent(run, grant));
                }
                if (Requests.Items.Count == 1) Requests.SelectedIndex = 0;
                status.Text = Requests.Items.Count == 0 ? "Ожидающих запросов нет."
                    : Requests.SelectedItem == null ? "Выберите запрос." : "Разрешите или отклоните запрос.";
            } else if (!closing) {
                status.Text = "Не удалось получить запросы.";
            }
            busy = false;
            RefreshButtons();
        }

        private async Task DecideAsync(bool allow) {
            var selected = Requests.SelectedItem as Consent;
            if (busy || closing || selected == null || active != null) return;
            busy = true;
            if (allow) active = selected;
            status.Text = "Отправляю решение.";
            RefreshButtons();
            var result = await SendAsync("POST", selected.Path("consent"),
                new { version = 1, grant_id = selected.GrantId, allow = allow });
            if (!closing && !stopping && (!allow || active == selected)) {
                var expected = allow ? "active" : "denied";
                bool confirmed = Matches(result, selected, expected);
                status.Text = !confirmed ? "Сервер не подтвердил решение."
                    : allow ? "Сервер принял разрешение. Нажмите «Остановить», чтобы отозвать его."
                    : "Запрос отклонён.";
                if (confirmed) Requests.Items.Remove(selected);
            }
            busy = false;
            RefreshButtons();
        }

        private Task StopAsync() {
            if (stopTask != null && !stopTask.IsCompleted) return stopTask;
            if (active == null) return Task.FromResult(false);
            stopTask = RevokeAsync(active);
            return stopTask;
        }

        private async Task RevokeAsync(Consent selected) {
            stopping = true;
            status.Text = "Отзываю разрешение.";
            RefreshButtons();
            var result = await SendAsync("POST", selected.Path("stop"), new { version = 1, grant_id = selected.GrantId });
            bool confirmed = Matches(result, selected, "stopped");
            if (confirmed) {
                active = null;
                Requests.Items.Remove(selected);
            }
            status.Text = confirmed ? "Разрешение отозвано." : "Сервер не подтвердил остановку.";
            stopping = false;
            RefreshButtons();
        }

        private async void OnClosing(object sender, CancelEventArgs args) {
            if (allowClose || active == null) { closing = true; return; }
            args.Cancel = true;
            if (closing) return;
            closing = true;
            RefreshButtons();
            await StopAsync();
            await Dispatcher.Yield(DispatcherPriority.Background);
            allowClose = true;
            Close();
        }

        private static bool Matches(Dictionary<string, object> result, Consent request, string expectedStatus) {
            return result != null && object.Equals(Json.Get(result, "version"), 1)
                && Json.Text(result, "mode") == "dry_run" && Json.Text(result, "grant_id") == request.GrantId
                && Json.Text(result, "status") == expectedStatus;
        }

        private async Task<Dictionary<string, object>> SendAsync(string method, string path, object data) {
            using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(4))) {
                try { return await client.ComputerUseLab(method, path, data, deadline.Token); }
                catch (ApiException) { }
                catch (HttpRequestException) { }
                catch (OperationCanceledException) { }
                catch (InvalidOperationException) { }
                catch (ArgumentException) { }
                return null;
            }
        }
    }
}
