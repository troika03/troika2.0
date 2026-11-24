using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using Troika.Desktop;

public static class BackgroundIntegrationTests {
    private static void Check(bool condition, string message) {
        if (!condition) throw new Exception(message);
    }
    private static void Reject(Action action, string message) {
        try { action(); }
        catch (InvalidOperationException) { return; }
        catch (InvalidDataException) { return; }
        throw new Exception(message);
    }
    public static int Main(string[] args) {
        string root = Path.Combine(Path.GetTempPath(), "troika-desktop-integration-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try {
            if (args.Length == 3 && args[0] == "--wake-audio") {
                var assets = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "voice-id");
                using (var extractor = new VoskVoiceSignatureExtractor(assets)) {
                    Check(RecognizeWake(extractor, args[1]), "Offline model recognizes the keyword");
                    Check(!RecognizeWake(extractor, args[2]), "Offline model rejects different speech");
                }
                Console.WriteLine("PASS real offline Vosk keyword and negative sample");
                return 0;
            }
            if (args.Contains("--live-codex")) {
                var executable = LocalCodex.FindExecutable("");
                Check(executable.Length > 0, "Installed Codex CLI");
                Check(LocalCodex.ChatGptConnected(executable, root, CancellationToken.None).GetAwaiter().GetResult(), "Saved ChatGPT login");
                var folder = Directory.CreateDirectory(Path.Combine(root, "project-20261125-a1a1a1a1")).FullName;
                using (var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(5))) {
                    var result = LocalCodex.Run(executable, root, folder,
                        "Create only a file named greeting.txt containing exactly TROIKA_CODEX_PROJECT_OK and a trailing newline. Then report completion.",
                        Console.WriteLine, deadline.Token).GetAwaiter().GetResult();
                    Check(result.Completed && File.ReadAllText(Path.Combine(folder, "greeting.txt")).Trim() == "TROIKA_CODEX_PROJECT_OK",
                        "Authenticated Codex wrote expected file in the approved project");
                }
                Console.WriteLine("PASS real ChatGPT-account Codex project");
                return 0;
            }
            Check(CodexVoiceRequest.Parse("Когда стоит использовать Codex?") == null, "Normal conversation stays local to Troika routing");
            Check(CodexVoiceRequest.Parse("Попроси Кодекс сделать проект").Task == "сделать проект", "Voice delegation");
            var delegated = CodexVoiceRequest.Parse("Тройка скажи Кодексу, чтобы он подготовил README.");
            Check(delegated != null && delegated.Task == "подготовил README.", "Spoken delegation with a subordinate clause");
            var chatProject = CodexVoiceRequest.Parse("Скажи кодексу, чтобы он в чате GPT создал новый проект и написал привет.");
            Check(chatProject != null && CodexVoiceRequest.TargetsChatGptProject(chatProject.Task), "Named ChatGPT project stays distinct from a folder-based Codex task");
            Check(CodexVoiceRequest.TargetsChatGptProject("создай в ChatGPT новый проект"), "ChatGPT destination can follow the verb");
            Check(!CodexVoiceRequest.TargetsChatGptProject("создай проект в ChatGPT Codex") &&
                !CodexVoiceRequest.TargetsChatGptProject("создай проект для интеграции с ChatGPT"), "Ordinary coding projects are delegated");
            Check(CodexVoiceRequest.Parse("Скажи, чем мне может помочь Кодекс?") == null, "General question about Codex stays in chat");
            Check(CodexVoiceRequest.Parse("Тройка, что делает Кодекс?").Action == "status", "Voice status");
            Check(CodexVoiceRequest.Parse("Останови Кодекс.").Action == "stop", "Voice stop");
            Check(CodexVoiceRequest.Parse("/codex сделай README").Task == "сделай README", "Explicit text delegation");
            Check(LocalFileRequest.Parse("Найди в интернете отчёт") == null, "Web tasks stay in ordinary chat");
            Check(LocalFileRequest.Parse("Покажи содержимое папки").Action == "list", "Voice list");
            Check(LocalFileRequest.Parse("А чё у меня последнее скачивалось в папке загрузка?").Action == "latest-download", "Colloquial Downloads question");
            Check(LocalFileRequest.Parse("Какая у меня последняя загрузка?").Action == "latest-download", "Most recent download");
            Check(LocalFileRequest.Parse("Что я скачал последним?").Action == "latest-download", "Recent download without a folder name");
            Check(LocalFileRequest.Parse("Найди в интернете последнюю загрузку дистрибутива") == null, "Online lookup stays in chat");
            Check(LocalFileRequest.Parse("Прочитай файл «заметка.txt».").Target == "заметка.txt", "Voice filename");
            Console.WriteLine("PASS explicit voice and text routing");

            var project = Directory.CreateDirectory(Path.Combine(root, "project-20261125-a1a1a1a1")).FullName;
            LocalCodex.ValidateProject(root, project);
            Reject(() => LocalCodex.ValidateProject(root, Path.Combine(root, "other")), "Unmanaged Codex folder accepted");
            var progress = new CodexProgress();
            progress.Read("{\"type\":\"item.completed\",\"item\":{\"type\":\"command_execution\",\"command\":\"private\",\"aggregated_output\":\"private\"}}");
            Check(!progress.Status.Contains("private") && !progress.Succeeded(0), "Process logs or premature success exposed");
            progress.Read("{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"готово\"}}");
            progress.Read("{\"type\":\"turn.completed\"}");
            Check(progress.Summary == "готово" && progress.Succeeded(0) && !progress.Succeeded(1), "A real completion requires a successful exit");
            Console.WriteLine("PASS Codex result and project boundaries");

            string folderPath = Directory.CreateDirectory(Path.Combine(root, "notes")).FullName;
            string textPath = Path.Combine(folderPath, "заметка.txt");
            File.WriteAllText(textPath, "Текст " + new string('а', 9000), Encoding.UTF8);
            Check(LocalFileAccess.Resolve(root, @"notes\заметка.txt") == textPath, "Relative local file");
            Check(LocalFileAccess.Find(root, "замет").Single() == textPath, "Find nested local file");
            Check(LocalFileAccess.ReadPreview(textPath).StartsWith("Текст ") && LocalFileAccess.ReadPreview(textPath).EndsWith("Показано начало файла."), "Limited Unicode preview");
            Reject(() => LocalFileAccess.Resolve(root, "..\\elsewhere"), "Path traversal accepted");
            Reject(() => LocalFileAccess.Resolve(root, "notes\\заметка.txt:stream"), "Alternate data stream accepted");
            Reject(() => LocalFileAccess.Resolve(root, root + "-outside\\secret.txt"), "Sibling-prefix path accepted");
            Console.WriteLine("PASS local file lookup, limits and containment");

            string recentFolder = Directory.CreateDirectory(Path.Combine(root, "recent")).FullName;
            Check(LocalFileAccess.LatestDownload(recentFolder) == null, "Empty Downloads folder");
            var day = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
            string oldDownload = Path.Combine(recentFolder, "old.txt");
            string newDownload = Path.Combine(recentFolder, "new.txt");
            string partialDownload = Path.Combine(recentFolder, "pending.crdownload");
            File.WriteAllText(oldDownload, "");
            File.WriteAllText(newDownload, "");
            File.WriteAllText(partialDownload, "");
            File.SetCreationTimeUtc(oldDownload, day);
            File.SetLastWriteTimeUtc(oldDownload, day.AddDays(4));
            File.SetCreationTimeUtc(newDownload, day.AddDays(1));
            File.SetLastWriteTimeUtc(newDownload, day.AddDays(-1));
            File.SetCreationTimeUtc(partialDownload, day.AddDays(3));
            Check(LocalFileAccess.LatestDownload(recentFolder).Name == "new.txt", "Newest completed arrival wins over modification time and partial downloads");
            Console.WriteLine("PASS newest finished download by creation time");

            var silence = new byte[3200];
            var speech = Enumerable.Range(0, 1600).SelectMany(_ => BitConverter.GetBytes((short)1800)).ToArray();
            using (var capture = new WakeCommandAudio()) {
                for (int i = 0; i < 4; i++) Check(capture.Append(speech, speech.Length), "Wake cue interval");
                for (int i = 0; i < 50; i++) capture.Append(silence, silence.Length);
                Check(capture.Result() == null, "Wake cue or silence submitted as a command");
            }
            using (var capture = new WakeCommandAudio()) {
                for (int i = 0; i < 4; i++) capture.Append(silence, silence.Length);
                for (int i = 0; i < 6; i++) capture.Append(speech, speech.Length);
                for (int i = 0; i < 10; i++) Check(capture.Append(silence, silence.Length), "Trailing interval ended too soon");
                Check(!capture.Append(silence, silence.Length), "Trailing silence did not finish recording");
                var wav = capture.Result();
                Check(wav.Length == 44 + 17 * 3200 && BitConverter.ToInt16(wav, 44) == 1800, "Only post-wake speech and trailing silence in WAV");
            }
            Console.WriteLine("PASS bounded post-wake recording");
            return 0;
        } finally {
            Directory.Delete(root, true);
        }
    }
    private static bool RecognizeWake(VoskVoiceSignatureExtractor extractor, string sample) {
        var wav = File.ReadAllBytes(sample);
        int start, length;
        VoskVoiceSignatureExtractor.PcmRange(wav, out start, out length);
        bool detected = false;
        Action<Func<byte[], int, bool>> feed = recognize => {
            var block = new byte[3200];
            for (var index = start; index < start + length && !detected; index += block.Length) {
                int count = Math.Min(block.Length, start + length - index);
                Buffer.BlockCopy(wav, index, block, 0, count);
                detected = recognize(block, count);
            }
        };
        var method = typeof(VoskVoiceSignatureExtractor).GetMethod("ListenForWake", BindingFlags.NonPublic | BindingFlags.Instance);
        method.Invoke(extractor, new object[] { feed, CancellationToken.None });
        return detected;
    }
}
