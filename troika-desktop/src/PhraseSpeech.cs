using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    // Complete phrases start immediately; at most two subsequent phrases prepare.
    public sealed class PhraseSpeech : IDisposable {
        private readonly Func<string, CancellationToken, Task<byte[]>> prepare;
        private readonly Func<byte[], CancellationToken, Task> play;
        private readonly CancellationTokenSource stop;
        private readonly CancellationToken token;
        private readonly Queue<string> pending = new Queue<string>();
        private readonly Queue<Task<byte[]>> ready = new Queue<Task<byte[]>>();
        private readonly TaskCompletionSource<bool> done = new TaskCompletionSource<bool>();
        private readonly object gate = new object();
        private string buffer = "";
        private bool closed, running, cancelled;
        private static readonly Regex boundary = new Regex(@"[!?…](?:\s|$)|\.\s|\n");

        public PhraseSpeech(Func<string, CancellationToken, Task<byte[]>> prepare, Func<byte[], CancellationToken, Task> play, CancellationToken cancellation) {
            this.prepare = prepare; this.play = play;
            stop = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
            token = stop.Token;
            token.Register(Cancel);
        }
        public void Add(string delta) {
            lock (gate) {
                if (closed || cancelled) return;
                buffer += delta;
                if (buffer.TrimStart().StartsWith("[emo:") && !buffer.Contains("]")) return;
                buffer = Regex.Replace(buffer, @"\[emo:\s*[^\]]*\]", "");
                while (buffer.Length > 0) {
                    var match = boundary.Match(buffer); int cut = match.Success ? match.Index + match.Length : 0;
                    if (cut == 0 && buffer.Length > 180) { cut = buffer.LastIndexOf(' ', 180); if (cut <= 0) cut = 180; }
                    if (cut == 0) break;
                    Enqueue(buffer.Substring(0, cut)); buffer = buffer.Substring(cut);
                }
                Prefetch(); Start();
            }
        }
        private void Enqueue(string text) { text = Regex.Replace(text, "[*#`]", "").Trim(); if (text.Length > 0 && pending.Count < 100) pending.Enqueue(text); }
        private void Prefetch() {
            while (!cancelled && ready.Count < 2 && pending.Count > 0) ready.Enqueue(prepare(pending.Dequeue(), token));
        }
        private void Start() { if (!running && !cancelled) { running = true; Drain(); } }
        private async void Drain() {
            try {
                while (true) {
                    Task<byte[]> next;
                    lock (gate) {
                        Prefetch();
                        if (cancelled || ready.Count == 0) { running = false; if (closed && !cancelled) done.TrySetResult(true); return; }
                        next = ready.Dequeue();
                    }
                    var audio = await next;
                    try {
                        token.ThrowIfCancellationRequested();
                        lock (gate) { Prefetch(); }
                        await play(audio, token);
                    } finally { Array.Clear(audio, 0, audio.Length); }
                }
            } catch (OperationCanceledException) { Cancel(); }
            catch (Exception error) { done.TrySetException(error); Cancel(); }
        }
        public Task Finish() { lock (gate) { if (!cancelled) { Enqueue(buffer); buffer = ""; closed = true; Start(); } return done.Task; } }
        public void Cancel() {
            lock (gate) {
                if (cancelled) return;
                cancelled = true; pending.Clear(); buffer = "";
                while (ready.Count > 0) ready.Dequeue().ContinueWith(task => { if (task.Status == TaskStatus.RanToCompletion) Array.Clear(task.Result, 0, task.Result.Length); else { var ignored = task.Exception; } });
                done.TrySetCanceled(); stop.Cancel();
            }
        }
        public void Dispose() { Cancel(); stop.Dispose(); }
    }
}
