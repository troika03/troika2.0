using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Troika.Desktop;

class PhraseSpeechTests {
    static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
    static void Main() { Run().GetAwaiter().GetResult(); Console.WriteLine("3 speech queue checks passed: early playback, order/prefetch, cancellation/clearing."); }
    static async Task Run() {
        var first = new TaskCompletionSource<bool>();
        var release = new TaskCompletionSource<bool>();
        var texts = new List<string>(); var played = new List<byte>(); int prepared = 0;
        var queue = new PhraseSpeech((text, token) => {
            lock (texts) { texts.Add(text); ++prepared; return Task.FromResult(new byte[] { (byte)prepared }); }
        }, async (audio, token) => {
            lock (played) { played.Add(audio[0]); }
            if (audio[0] == 1) { first.TrySetResult(true); await release.Task; }
        }, CancellationToken.None);
        queue.Add("[emo:"); queue.Add("joy] Привет! Вторая фраза. Третья. Четвёртая.");
        Assert(await Task.WhenAny(first.Task, Task.Delay(2000)) == first.Task, "first phrase waited for full reply");
        Assert(played.Count == 1 && prepared <= 3 && texts[0] == "Привет!", "prefetch or hidden tag broken");
        queue.Add(" Последняя часть"); release.TrySetResult(true); await queue.Finish();
        Assert(played.Count == 5 && played[0] == 1 && played[4] == 5, "reply reordered or repeated");

        var pending = new TaskCompletionSource<byte[]>(); bool stalePlayed = false;
        var cancelled = new PhraseSpeech((text, token) => pending.Task, (audio, token) => { stalePlayed = true; return Task.FromResult(0); }, CancellationToken.None);
        cancelled.Add("Проверка!"); cancelled.Cancel(); var bytes = new byte[] { 42 }; pending.SetResult(bytes);
        await Task.Delay(50);
        Assert(!stalePlayed && bytes[0] == 0, "cancelled audio escaped or was retained");
        try { await cancelled.Finish(); throw new Exception("cancelled queue reported success"); } catch (OperationCanceledException) { }
    }
}
