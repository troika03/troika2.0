using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows;
using System.Windows.Controls;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private sealed class CodexCard {
            public TextBlock Status;
            public Button OpenChat, Stop;
            public CancellationTokenSource Run;
            public string Folder, Conversation;
        }
        private CodexCard codexCard;

        private bool CodexOwnerCurrent(string owner) { return !closed && api.Account.SignedIn && api.Account.Email == owner; }
        private CodexConversationLink CurrentCodexProject() {
            return api.Account.SignedIn ? new CodexConversationStore(store, api.Account.Email).Read(api.SessionId) : null;
        }
        private string CodexRoutingPreference(string owner) { return Path.Combine(store.FilesFolder(owner), ".codex-chat-disabled"); }
        private bool CodexRoutingEnabled(string owner) { return !File.Exists(CodexRoutingPreference(owner)); }
        private void SetCodexRouting(string owner, bool enabled) {
            if (!CodexOwnerCurrent(owner)) return;
            try {
                var path = CodexRoutingPreference(owner);
                if (enabled) File.Delete(path);
                else LocalStore.WriteAtomic(path, new byte[0]);
            } catch (Exception error) { SetStatus(error.Message, true); }
        }
        private string AutomaticCodexIntent(string input) {
            if (preview || !CodexRoutingEnabled(api.Account.Email)) return "";
            return CodexDevelopmentIntent.Match(input, CurrentCodexProject() != null);
        }
        private List<Dictionary<string, object>> ConversationsWithCodex() {
            if (!api.Account.SignedIn) return sessions;
            var known = new HashSet<string>(sessions.Select(item => Json.Text(item, "id")));
            var local = new CodexConversationStore(store, api.Account.Email).Recent().Where(project => known.Add(project.Conversation))
                .Select(project => new Dictionary<string, object> {
                    { "id", project.Conversation }, { "title", "Проект Codex · " + Path.GetFileName(project.Folder) }, { "codex_local_only", true }
                });
            return local.Concat(sessions).Take(30).ToList();
        }
        private void RestoreCodexCard(CodexConversationLink project) {
            if (project == null) return;
            bool running = codexRun != null && codexOwner == api.Account.Email && codexSession == project.Conversation;
            ShowCodexCard(project, running ? codexState : "Проект подключён к этому разговору.", running ? codexRun : null);
        }
        private void ShowCodexCard(CodexConversationLink project, string statusLine, CancellationTokenSource run) {
            if (api.SessionId != project.Conversation) return;
            ShowConversation();
            var block = new StackPanel { Margin = new Thickness(0, 5, 0, 26) };
            block.Children.Add(Label("Codex · " + Path.GetFileName(project.Folder), 14, text));
            var state = Label(statusLine, 13, muted); state.Margin = new Thickness(0, 6, 0, 10);
            block.Children.Add(state);
            Button open = null;
            open = Button("Открыть чат в Codex", () => OpenCodexThread((string)open.Tag), true);
            open.Tag = project.Thread;
            open.IsEnabled = project.Thread.Length > 0;
            var browse = Button("Открыть папку", () => OpenCodexWorkspace(project.Folder), false);
            var stopWork = Button("Остановить задачу", () => { if (run != null && codexRun == run) StopCodex(); }, false);
            stopWork.Visibility = run == null ? Visibility.Collapsed : Visibility.Visible;
            var actions = new WrapPanel();
            actions.Children.Add(open); actions.Children.Add(browse); actions.Children.Add(stopWork);
            block.Children.Add(actions); transcript.Children.Add(block); conversationScroll.ScrollToEnd();
            codexCard = new CodexCard { Status = state, OpenChat = open, Stop = stopWork, Run = run, Folder = project.Folder, Conversation = project.Conversation };
        }
        private void RememberCodexThread(string owner, CodexConversationLink project) {
            new CodexConversationStore(store, owner).Save(project);
            if (codexCard == null || codexCard.Folder != project.Folder || codexCard.Conversation != project.Conversation) return;
            codexCard.OpenChat.Tag = project.Thread;
            codexCard.OpenChat.IsEnabled = project.Thread.Length > 0;
        }
        private void OpenCodexThread(string thread) {
            try { Process.Start(new ProcessStartInfo(CodexConversationLink.ThreadUrl(thread)) { UseShellExecute = true }); }
            catch { SetStatus("Windows не смогла открыть чат. Проверьте установку приложения ChatGPT с Codex.", true); }
        }
        private void OpenCodexWorkspace(string folder) {
            try { Process.Start(new ProcessStartInfo(LocalCodex.ValidateWorkspace(folder)) { UseShellExecute = true }); }
            catch (Exception error) { SetStatus(error.Message, true); }
        }
    }
}
