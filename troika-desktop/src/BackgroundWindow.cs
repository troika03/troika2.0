using System;
using System.Linq;
using System.Windows;
using Forms = System.Windows.Forms;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private Forms.NotifyIcon projectTray;
        private bool exitRequested;
        private bool KeepProjectsInBackground() {
            if (preview || exitRequested || autopilot == null ||
                !autopilot.Projects.Any(p => !DevelopmentAutopilot.Terminal(Json.Text(p, "status")))) return false;
            if (projectTray == null) {
                projectTray = new Forms.NotifyIcon { Text = "Тройка — проекты работают в фоне", Icon = System.Drawing.SystemIcons.Application };
                var menu = new Forms.ContextMenuStrip();
                menu.Items.Add("Открыть Тройку", null, (s, e) => Dispatcher.BeginInvoke(new Action(ShowFromTray)));
                menu.Items.Add("Прервать голосовой отчёт", null, (s, e) => Dispatcher.BeginInvoke(new Action(() => { if (projectSpeech != null) projectSpeech.Cancel(); StopPlayback(); })));
                menu.Items.Add("Выйти из Тройки", null, (s, e) => Dispatcher.BeginInvoke(new Action(() => { exitRequested = true; Close(); })));
                projectTray.ContextMenuStrip = menu;
                projectTray.DoubleClick += (s, e) => Dispatcher.BeginInvoke(new Action(ShowFromTray));
            }
            projectTray.Visible = true; Hide();
            projectTray.ShowBalloonTip(4000, "Тройка работает в фоне", "Проекты сохранятся на ПК. Голосовые отчёты включаются во вкладке «Разработка». Выход — через значок Тройки.", Forms.ToolTipIcon.Info);
            return true;
        }
        private void ShowFromTray() { Show(); if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal; Activate(); }
        private void DisposeProjectTray() { if (projectTray != null) { projectTray.Visible = false; projectTray.Dispose(); projectTray = null; } }
    }
}
