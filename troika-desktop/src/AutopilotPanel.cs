using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using System.Windows.Media;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private DevelopmentAutopilot autopilot;
        private DispatcherTimer autopilotTimer;
        private StackPanel autopilotCards;
        private bool autopilotSpeaking;
        private CancellationTokenSource projectSpeech;
        private DevelopmentAutopilot Autopilot { get { return autopilot ?? (autopilot = new DevelopmentAutopilot(api, store) { OnAccountChanged = () => { if (projectSpeech != null) projectSpeech.Cancel(); } }); } }
        private void ObserveAutopilot() {
            if (autopilotTimer == null) {
                autopilotTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(4) };
                autopilotTimer.Tick += async delegate {
                    if (closed) { autopilotTimer.Stop(); return; }
                    await Autopilot.Refresh(CancellationToken.None);
                    if (openPanel == "Разработка" && autopilotCards != null) RenderAutopilotCards();
                    await SpeakProjectReport();
                };
                autopilotTimer.Start();
            }
            var pending = Autopilot.Refresh(CancellationToken.None);
        }
        private async Task StartAutopilot(string task, System.Collections.Generic.Dictionary<string, string> sources = null) {
            if (!api.Account.SignedIn) { await OpenPanelTask("Аккаунт"); return; }
            if (task.Trim().Length == 0) { SetStatus("Опишите проект.", true); return; }
            await Safe(async () => { await Autopilot.Start(task, sources, CancellationToken.None); if (!busy && !speaking && !recorder.Recording) SetStatus("Автопилот запущен. Разговор остаётся доступным.", false); if (openPanel == "Разработка") RenderAutopilotCards(); });
        }
        private void RenderAutopilotCards() {
            autopilotCards.Children.Clear();
            if (!Autopilot.IsPro) autopilotCards.Children.Add(Label("Автопилот разработки доступен только в Pro.", 12, muted));
            if (Autopilot.Error.Length > 0) autopilotCards.Children.Add(Label(Autopilot.Error, 12, muted));
            foreach (var project in Autopilot.Projects) {
                var card = new StackPanel { Margin = new Thickness(0, 8, 0, 8) }; var id = Json.Text(project, "run_id");
                card.Children.Add(Label(Json.Text(project, "title"), 15, text));
                card.Children.Add(Label(DevelopmentAutopilot.Stage(Json.Text(project, "stage")), 12, muted));
                var count = Json.Rows(project, "workers").Count(w => Json.Text(w, "status") == "running");
                if (!DevelopmentAutopilot.Terminal(Json.Text(project, "status"))) {
                    card.Children.Add(Label("Работают специалисты: " + count + ". Можно вернуться к разговору.", 11, muted));
                    card.Children.Add(Button("Остановить проект", () => { var pending = Safe(async () => { await Autopilot.Stop(id, CancellationToken.None); await Autopilot.Refresh(CancellationToken.None); RenderAutopilotCards(); }); }, false));
                }
                if (Autopilot.Results.ContainsKey(id)) { var folder = Autopilot.Results[id]; card.Children.Add(Button("Показать результат", () => { if (File.Exists(folder)) OpenFile(folder); else { projectFolder = folder; checkReport = null; RenderDevelopment(); } }, true)); }
                if (Json.Text(project, "delivery_error").Length > 0) card.Children.Add(Label(Json.Text(project, "delivery_error"), 11, muted));
                var reports = new StackPanel(); foreach (var report in Json.Rows(project, "reports")) reports.Children.Add(Label(Json.Text(report, "text"), 12, muted));
                if (reports.Children.Count > 0) card.Children.Add(new Expander { Header = "Отчёты Тройки", Content = reports, Margin = new Thickness(0, 8, 0, 8) });
                autopilotCards.Children.Add(card);
            }
        }
        private async Task SpeakProjectReport() {
            if (autopilotSpeaking || busy || speaking || recorder.Recording || pendingApproval != null || closed) return;
            var report = Autopilot.NextReport(true); if (report == null) return;
            autopilotSpeaking = true; var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(60)); projectSpeech = cancellation; var identity = api.Account.Email; string reportFile = "";
            try {
                var bytes = await api.Speech(report.Text, cancellation.Token);
                if (busy || speaking || recorder.Recording || closed || cancellation.IsCancellationRequested || identity != api.Account.Email) { Array.Clear(bytes, 0, bytes.Length); return; }
                var completed = new TaskCompletionSource<bool>(); EventHandler ended = (s, e) => completed.TrySetResult(true);
                EventHandler<ExceptionEventArgs> failed = (s, e) => completed.TrySetResult(false);
                player.MediaEnded += ended; player.MediaFailed += failed;
                try {
                    var folder = Path.Combine(store.Root, "audio"); Directory.CreateDirectory(folder); audioFile = Path.Combine(folder, Guid.NewGuid().ToString("N") + ".mp3"); reportFile = audioFile; File.WriteAllBytes(audioFile, bytes); Array.Clear(bytes, 0, bytes.Length);
                    speaking = true; player.Open(new Uri(audioFile)); player.Play(); orb.SetState("speaking"); microphone.Content = "Прервать";
                    using (cancellation.Token.Register(() => completed.TrySetResult(false))) { if (await completed.Task) Autopilot.ReportSpoken(report); }
                } finally { player.MediaEnded -= ended; player.MediaFailed -= failed; if (audioFile == reportFile) StopPlayback(); if (!busy && !recorder.Recording && !speaking) Idle(); }
            } catch { /* Visible reports remain available when voice fails. */ }
            finally { if (projectSpeech == cancellation) projectSpeech = null; cancellation.Dispose(); autopilotSpeaking = false; }
        }
        private void DisposeAutopilotObserver() { if (autopilotTimer != null) autopilotTimer.Stop(); if (projectSpeech != null) projectSpeech.Cancel(); }
    }
}
