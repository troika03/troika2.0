using System;
using System.Linq;
using System.Windows;
using Forms = System.Windows.Forms;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private Forms.NotifyIcon projectTray;
        private Forms.ToolStripMenuItem wakeTrayEntry, codexTrayEntry, stopCodexTrayEntry;
        private bool exitRequested;
        private bool KeepProjectsInBackground() {
            if (preview || exitRequested || !WakeEnabledForAccount && codexRun == null &&
                (autopilot == null || !autopilot.Projects.Any(p => !DevelopmentAutopilot.Terminal(Json.Text(p, "status"))))) return false;
            EnsureBackgroundTray();
            Hide();
            RefreshBackgroundTray();
            return true;
        }
        private void EnsureBackgroundTray() {
            if (projectTray == null) {
                projectTray = new Forms.NotifyIcon { Text = "Тройка — проекты работают в фоне", Icon = System.Drawing.SystemIcons.Application };
                var menu = new Forms.ContextMenuStrip();
                menu.Items.Add("Открыть Тройку", null, (s, e) => Dispatcher.BeginInvoke(new Action(ShowFromTray)));
                wakeTrayEntry = (Forms.ToolStripMenuItem)menu.Items.Add("Выключить фоновый микрофон", null, (s, e) => Dispatcher.BeginInvoke(new Action(() => SetWakeEnabled(false))));
                codexTrayEntry = (Forms.ToolStripMenuItem)menu.Items.Add("Открыть проект Codex", null, (s, e) => Dispatcher.BeginInvoke(new Action(() => { ShowFromTray(); OpenPanel("Codex"); })));
                stopCodexTrayEntry = (Forms.ToolStripMenuItem)menu.Items.Add("Остановить Codex", null, (s, e) => Dispatcher.BeginInvoke(new Action(StopCodex)));
                menu.Items.Add("Прервать голосовой отчёт", null, (s, e) => Dispatcher.BeginInvoke(new Action(() => { if (projectSpeech != null) projectSpeech.Cancel(); StopPlayback(); })));
                menu.Items.Add("Выйти из Тройки", null, (s, e) => Dispatcher.BeginInvoke(new Action(() => { exitRequested = true; Close(); })));
                projectTray.ContextMenuStrip = menu;
                projectTray.DoubleClick += (s, e) => Dispatcher.BeginInvoke(new Action(ShowFromTray));
            }
        }
        private void RefreshBackgroundTray() {
            if (closed || preview || exitRequested) return;
            bool visible = WakeEnabledForAccount || codexRun != null || !IsVisible && projectTray != null;
            if (visible) EnsureBackgroundTray();
            if (projectTray == null) return;
            wakeTrayEntry.Visible = WakeEnabledForAccount;
            codexTrayEntry.Visible = codexRun != null || codexFolder.Length > 0;
            stopCodexTrayEntry.Visible = codexRun != null;
            string hint = wakeRecording ? "Тройка — записывает команду" : wakeReady ? "Тройка — ждёт слово «Тройка»"
                : codexRun != null ? "Тройка — Codex работает в фоне" : "Тройка работает в фоне";
            if (projectTray.Text != hint) projectTray.Text = hint;
            if (projectTray.Visible != visible) projectTray.Visible = visible;
        }
        private void ShowFromTray() { if (!IsVisible) Show(); if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal; Activate(); }
        private void DisposeProjectTray() {
            if (projectTray == null) return;
            projectTray.Visible = false;
            projectTray.ContextMenuStrip.Dispose();
            projectTray.Dispose();
            projectTray = null;
        }
    }
}
