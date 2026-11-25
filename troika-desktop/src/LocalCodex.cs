using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed class CodexVoiceRequest {
        public readonly string Action, Task;
        private CodexVoiceRequest(string action, string task) { Action = action; Task = task; }
        private const string Codex = @"(?:codex|кодекс(?:а|у|ом)?)";
        private const RegexOptions IgnoreCase = RegexOptions.IgnoreCase | RegexOptions.CultureInvariant;
        private static readonly Regex Start = new Regex(@"^(?:/codex(?:\s+|$)|(?:скажи|напиши|попроси|поручи|передай)(?:\s+(?:задачу|проект))?\s+" + Codex + @"\b|(?:через|запусти)\s+" + Codex + @"\b|" + Codex + @"\s*[:,])\s*[:,—-]?\s*(.*)$", IgnoreCase | RegexOptions.Singleline);
        private static readonly Regex ChatGptLocation = new Regex(@"\b(?:в|на)\s+(?:(?:чате|приложении|сайте|веб-версии)\s+)?(?:chat\s*gpt|чат(?:е)?\s*(?:gpt|гпт|джи\s*пи\s*ти)|gpt)\b(?!\s+(?:codex|кодекс[аеу]?)\b)", IgnoreCase);
        private static readonly Regex ProjectCreation = new Regex(@"\b(?:созда[а-яё]*|сдела[а-яё]*|заве[а-яё]*)\b[^.!?;,\r\n]{1,65}\bпроект\b", IgnoreCase);
        public static CodexVoiceRequest Parse(string input) {
            string phrase = Regex.Replace((input ?? "").Trim(), @"^тройка(?:\s*[:,—-]\s*|\s+)", "", IgnoreCase);
            string command = phrase.TrimEnd('.', '!', '?');
            if (Regex.IsMatch(command, @"^(?:останови|прерви)\s+" + Codex + "$", IgnoreCase) || command.Equals("/codex stop", StringComparison.OrdinalIgnoreCase)) return new CodexVoiceRequest("stop", "");
            if (Regex.IsMatch(command, @"^(?:что делает|статус)\s+" + Codex + "$", IgnoreCase) || command.Equals("/codex status", StringComparison.OrdinalIgnoreCase)) return new CodexVoiceRequest("status", "");
            var match = Start.Match(phrase);
            if (!match.Success) return null;
            string task = match.Groups[1].Value.Trim();
            if (!phrase.StartsWith("/codex", StringComparison.OrdinalIgnoreCase))
                task = Regex.Replace(task, @"^чтобы\s+(?:(?:он|тот|" + Codex + @")\s+)?", "", IgnoreCase);
            return new CodexVoiceRequest("start", task.Trim('.', '!', '?').Length == 0 ? "" : task);
        }
        public static bool TargetsChatGptProject(string task) {
            return ChatGptLocation.IsMatch(task) && ProjectCreation.IsMatch(task);
        }
    }

    public sealed class CodexProgress {
        public string Status = "Запускаю Codex";
        public string Summary = "";
        public string ThreadId = "";
        internal string Failure = "";
        public bool Completed, Failed;
        public bool Read(string line) {
            if (string.IsNullOrWhiteSpace(line) || !line.StartsWith("{", StringComparison.Ordinal)) return false;
            var data = Json.Parse(line);
            string previous = Status;
            switch (Json.Text(data, "type")) {
                case "thread.started":
                    ThreadId = CodexConversationLink.NormalizeThread(Json.Text(data, "thread_id"));
                    Status = "Codex подключился к проекту";
                    break;
                case "turn.started": Status = "Codex работает над задачей"; break;
                case "item.started":
                case "item.completed":
                    var item = Json.Map(Json.Get(data, "item"));
                    switch (Json.Text(item, "type")) {
                        case "file_change": Status = "Codex меняет файлы проекта"; break;
                        case "command_execution": Status = "Codex выполняет работу в папке проекта"; break;
                        case "todo_list": Status = "Codex обновляет план"; break;
                        case "agent_message":
                            if (Json.Text(data, "type") == "item.completed") {
                                var message = Json.Text(item, "text");
                                Summary = message.Length > 10000 ? message.Substring(0, 10000) : message;
                            }
                            break;
                    }
                    break;
                case "turn.completed": Completed = true; break;
                case "error": Failure = Json.Text(data, "message"); break;
                case "turn.failed":
                    Failed = true;
                    var detail = Json.Text(Json.Map(Json.Get(data, "error")), "message");
                    if (detail.Length > 0) Failure = detail;
                    break;
            }
            return previous != Status;
        }
        public bool Succeeded(int exitCode) { return exitCode == 0 && Completed && !Failed; }
    }

    public static class LocalCodex {
        private static readonly string Config = string.Join(" ", new[] {
            "windows.sandbox=\"mxc\"",
            "permissions.troika-local.extends=\":workspace\"",
            "permissions.troika-local.filesystem={\":root\"=\"deny\",\":minimal\"=\"read\",\":tmpdir\"=\"deny\",\":slash_tmp\"=\"deny\",glob_scan_max_depth=6,\":workspace_roots\"={\".\"=\"write\",\"**/.env\"=\"deny\",\"**/.env.*\"=\"deny\",\"**/.ssh\"=\"deny\",\"**/.codex/auth.json\"=\"deny\"}}",
            "permissions.troika-local.network.enabled=false"
        }.Select(value => "-c " + Quote(value)));
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        private static extern int GetPackagesByPackageFamily(string family, ref uint count, IntPtr names, ref uint length, IntPtr buffer);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        private static extern int GetPackagePathByFullName(string name, ref uint length, StringBuilder path);

        private static string InstalledDesktopCodex() {
            const string family = "OpenAI.Codex_2p2nqsd0c76g0";
            uint count = 0, length = 0;
            if (GetPackagesByPackageFamily(family, ref count, IntPtr.Zero, ref length, IntPtr.Zero) != 122 || count == 0 || count > 32 || length > 32768) return "";
            var names = Marshal.AllocHGlobal((int)count * IntPtr.Size);
            var buffer = Marshal.AllocHGlobal((int)length * 2);
            try {
                if (GetPackagesByPackageFamily(family, ref count, names, ref length, buffer) != 0) return "";
                for (int i = 0; i < count; i++) {
                    var name = Marshal.PtrToStringUni(Marshal.ReadIntPtr(names, i * IntPtr.Size));
                    uint maximum = 1024;
                    var path = new StringBuilder((int)maximum);
                    if (GetPackagePathByFullName(name, ref maximum, path) != 0) continue;
                    var candidate = Path.Combine(path.ToString(), "app", "resources", "codex.exe");
                    if (IsExecutable(candidate)) return candidate;
                }
                return "";
            } finally {
                Marshal.FreeHGlobal(buffer);
                Marshal.FreeHGlobal(names);
            }
        }
        public static string FindExecutable(string configured) {
            if (IsExecutable(configured)) return configured;
            string installed = InstalledDesktopCodex();
            if (installed.Length > 0) return installed;
            foreach (var folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';')) {
                try {
                    if (!Path.IsPathRooted(folder)) continue;
                    var candidate = Path.Combine(folder, "codex.exe");
                    if (IsExecutable(candidate)) return candidate;
                } catch (ArgumentException) { }
            }
            string npm = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "npm", "node_modules", "@openai", "codex");
            string vendor = Path.Combine(npm, "node_modules", "@openai", "codex-win32-x64", "vendor", "x86_64-pc-windows-msvc");
            foreach (var candidate in new[] { Path.Combine(vendor, "codex", "codex.exe"), Path.Combine(vendor, "bin", "codex.exe") })
                if (IsExecutable(candidate)) return candidate;
            return "";
        }
        private static bool IsExecutable(string path) {
            try { return !string.IsNullOrEmpty(path) && Path.IsPathRooted(path) && Path.GetFileName(path).Equals("codex.exe", StringComparison.OrdinalIgnoreCase) && File.Exists(path); }
            catch (ArgumentException) { return false; }
        }
        private static string Quote(string arg) {
            return "\"" + Regex.Replace(arg, "(\\\\*)(\"|$)", match => {
                int count = match.Groups[1].Length;
                return new string('\\', count * 2 + (match.Groups[2].Length == 0 ? 0 : 1)) + match.Groups[2].Value;
            }) + "\"";
        }
        public static string ProjectRoot(LocalStore store, string owner, string location = "") {
            return Path.Combine(location.Length == 0 ? Path.Combine(store.Root, "codex-projects") : Path.Combine(location, "Troika Codex"),
                LocalStore.Hash(Encoding.UTF8.GetBytes(owner.ToLowerInvariant())).Substring(0, 24));
        }
        public static void ValidateProject(string root, string folder) {
            if (!string.Equals(Path.GetDirectoryName(folder), root, StringComparison.OrdinalIgnoreCase)
                || !Regex.IsMatch(Path.GetFileName(folder), @"^project-\d{8}-[0-9a-f]{8}$"))
                throw new InvalidOperationException("Выберите папку проекта из списка Codex.");
            for (var entry = new DirectoryInfo(folder); entry != null; entry = entry.Parent)
                if (entry.Exists && (entry.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("Папки проекта Codex должны быть обычными папками Windows.");
        }
        public static string ValidateWorkspace(string folder) {
            string path = LocalFileAccess.ValidateRoot(folder);
            string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            string appData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string generated = Path.Combine(appData, "TroikaDesktop", "codex-projects");
            if (IsInside(profile, path) || IsInside(path, Path.Combine(profile, ".codex"))
                || IsInside(path, Path.Combine(profile, ".ssh")) || IsInside(path, Path.Combine(profile, ".gnupg"))
                || IsInside(path, Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData))
                || IsInside(path, Environment.GetFolderPath(Environment.SpecialFolder.Windows))
                || IsInside(path, Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles))
                || IsInside(path, Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86))
                || IsInside(path, appData) && !IsInside(path, generated))
                throw new InvalidOperationException("Выберите отдельную папку с исходниками проекта.");
            return path;
        }
        private static bool IsInside(string path, string root) {
            return root.Length > 0 && (path.Equals(root, StringComparison.OrdinalIgnoreCase) ||
                path.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase));
        }
        public static async Task<bool> ChatGptConnected(string executable, string workingDirectory, CancellationToken cancellation) {
            var result = await Execute(executable, "-c forced_login_method=chatgpt login status", workingDirectory, null, null, cancellation).ConfigureAwait(false);
            return result.ExitCode == 0 && (result.Output + "\n" + result.Error)
                .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).Any(line => line.Trim() == "Logged in using ChatGPT");
        }
        public static async Task SignIn(string executable, string workingDirectory, CancellationToken cancellation) {
            var result = await Execute(executable, "-c forced_login_method=chatgpt login", workingDirectory, null, null, cancellation).ConfigureAwait(false);
            if (result.ExitCode != 0 || !await ChatGptConnected(executable, workingDirectory, cancellation).ConfigureAwait(false))
                throw new InvalidOperationException("Вход в ChatGPT не подтверждён. Повторите вход в браузере или войдите в Codex вручную.");
        }
        public static Task<CodexProgress> Run(string executable, string root, string folder, string task, Action<string> onProgress, CancellationToken cancellation) {
            return RunCore(executable, folder, task, () => ValidateProject(root, folder), onProgress, null, "", cancellation);
        }
        public static Task<CodexProgress> RunInChat(string executable, CodexConversationLink chat, string task,
            Action<string> onProgress, Action<string> onThread, CancellationToken cancellation) {
            if (onThread == null) throw new ArgumentNullException("onThread");
            return RunCore(executable, chat.Folder, task, () => ValidateWorkspace(chat.Folder),
                onProgress, onThread, chat.Thread, cancellation);
        }
        public static string ExecutionArguments(bool saveChat, string resumeThread) {
            string arguments = "-c forced_login_method=chatgpt --ask-for-approval never " + Config
                + " -c default_permissions=troika-local -c allow_login_shell=false -c shell_environment_policy.inherit=none"
                + " -c project_root_markers=[] -c project_doc_max_bytes=0 -c web_search=disabled --disable hooks --disable shell_snapshot"
                + " exec --ignore-user-config --ignore-rules --strict-config --json --color never --skip-git-repo-check";
            if (!saveChat) return arguments + " --ephemeral -";
            return arguments + (resumeThread.Length == 0 ? " -" : " resume " + Quote(CodexConversationLink.NormalizeThread(resumeThread)) + " -");
        }
        private static async Task<CodexProgress> RunCore(string executable, string folder, string task, Action validate,
            Action<string> onProgress, Action<string> onThread, string resumeThread, CancellationToken cancellation) {
            validate();
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation)) {
                deadline.CancelAfter(TimeSpan.FromSeconds(40));
                if (!await ChatGptConnected(executable, folder, deadline.Token).ConfigureAwait(false))
                    throw new InvalidOperationException("Сначала подключите аккаунт ChatGPT в разделе Codex.");
                var hostname = Path.Combine(Environment.SystemDirectory, "hostname.exe");
                var check = await Execute(executable, Config + " sandbox --include-managed-config --permission-profile troika-local --cd "
                    + Quote(folder) + " -- " + Quote(hostname), folder, null, null, deadline.Token).ConfigureAwait(false);
                if (check.ExitCode != 0 || !check.Output.Trim().Equals(Environment.MachineName, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Изоляция Codex для Windows недоступна. Обновите Codex и проверьте поддержку Windows MXC.");
            }
            validate();
            var progress = new CodexProgress();
            string prompt = "Выполни задачу в текущей папке проекта. Если папка уже содержит проект, "
                + "сначала изучи его и сохрани существующую работу. Подготовь понятную инструкцию запуска. "
                + "В конце кратко опиши результат и какие проверки действительно выполнил.\n\nЗадача пользователя:\n" + task;
            var run = await Execute(executable, ExecutionArguments(onThread != null, resumeThread), folder, prompt, line => {
                string previousThread = progress.ThreadId;
                if (progress.Read(line)) onProgress(progress.Status);
                if (onThread != null && progress.ThreadId != previousThread) {
                    if (resumeThread.Length > 0 && progress.ThreadId != resumeThread)
                        throw new InvalidDataException("Codex открыл неожиданный чат проекта.");
                    onThread(progress.ThreadId);
                }
            }, cancellation).ConfigureAwait(false);
            if (!progress.Succeeded(run.ExitCode)) {
                if (run.Error.IndexOf("already has an active writer", StringComparison.OrdinalIgnoreCase) >= 0 ||
                    progress.Failure.IndexOf("already has an active writer", StringComparison.OrdinalIgnoreCase) >= 0)
                    throw new InvalidOperationException("Чат открыт для работы в Codex. Завершите или закройте его там и повторите запрос в Тройке.");
                if (run.Error.IndexOf("failed to load AGENTS.md", StringComparison.OrdinalIgnoreCase) >= 0)
                    throw new InvalidOperationException("Codex не смог открыть рабочую папку. Выберите папку для проектов вне другого репозитория.");
                throw new InvalidOperationException("Codex не завершил задачу. Сохранённые файлы доступны в папке проекта. Проверьте вход, лимит или доступность Codex.");
            }
            if (onThread != null && progress.ThreadId.Length == 0)
                throw new InvalidOperationException("Codex завершил задачу без ссылки на сохранённый чат.");
            return progress;
        }
        private sealed class ProcessResult {
            public int ExitCode;
            public string Output, Error;
        }
        private static async Task<ProcessResult> Execute(string executable, string arguments, string folder, string input, Action<string> receive, CancellationToken cancellation) {
            cancellation.ThrowIfCancellationRequested();
            var settings = new ProcessStartInfo(executable, arguments) {
                WorkingDirectory = folder,
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            var inherited = settings.EnvironmentVariables;
            var allowed = new HashSet<string>(new[] { "APPDATA", "LOCALAPPDATA", "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                "SystemRoot", "SystemDrive", "windir", "TEMP", "TMP", "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH", "PATH", "PATHEXT", "ComSpec" }, StringComparer.OrdinalIgnoreCase);
            foreach (string key in inherited.Keys.Cast<string>().ToArray()) if (!allowed.Contains(key)) inherited.Remove(key);
            using (var job = new CodexProcessJob())
            using (var process = Process.Start(settings)) {
                if (process == null) throw new InvalidOperationException("Windows не смогла запустить Codex.");
                try { job.Attach(process); }
                catch { try { if (!process.HasExited) process.Kill(); } catch (InvalidOperationException) { } throw; }
                using (cancellation.Register(job.Stop)) {
                    var errorTask = process.StandardError.ReadToEndAsync();
                    var outputTask = ReadOutput(process.StandardOutput, receive);
                    var exited = Task.Run(() => process.WaitForExit());
                    System.Runtime.ExceptionServices.ExceptionDispatchInfo failure;
                    try {
                        if (input != null) {
                            var bytes = Encoding.UTF8.GetBytes(input);
                            try { await process.StandardInput.BaseStream.WriteAsync(bytes, 0, bytes.Length, cancellation).ConfigureAwait(false); }
                            finally { Array.Clear(bytes, 0, bytes.Length); }
                        }
                        process.StandardInput.Close();
                        string output = await outputTask.ConfigureAwait(false);
                        await exited.ConfigureAwait(false);
                        var error = await errorTask.ConfigureAwait(false);
                        cancellation.ThrowIfCancellationRequested();
                        return new ProcessResult { ExitCode = process.ExitCode, Output = output, Error = error };
                    } catch (Exception error) {
                        job.Stop();
                        failure = System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error);
                    }
                    await exited.ConfigureAwait(false);
                    cancellation.ThrowIfCancellationRequested();
                    failure.Throw();
                    throw new InvalidOperationException();
                }
            }
        }
        private static async Task<string> ReadOutput(StreamReader reader, Action<string> receive) {
            if (receive == null) return await reader.ReadToEndAsync().ConfigureAwait(false);
            string line;
            while ((line = await reader.ReadLineAsync().ConfigureAwait(false)) != null) receive(line);
            return "";
        }
    }

    internal sealed class CodexProcessJob : IDisposable {
        [StructLayout(LayoutKind.Sequential)] private struct Limits {
            public long ProcessTime, JobTime;
            public uint Flags;
            public UIntPtr MinWorkingSet, MaxWorkingSet;
            public uint ProcessLimit;
            public UIntPtr Affinity;
            public uint Priority, Scheduling;
            public ulong Reads, Writes, Other, ReadBytes, WriteBytes, OtherBytes;
            public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr CreateJobObject(IntPtr security, string name);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetInformationJobObject(IntPtr job, int information, ref Limits limits, int size);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
        private IntPtr handle;
        public CodexProcessJob() {
            handle = CreateJobObject(IntPtr.Zero, null);
            var limits = new Limits { Flags = 0x2000 }; // Kill children when the job closes.
            if (handle == IntPtr.Zero || !SetInformationJobObject(handle, 9, ref limits, Marshal.SizeOf(typeof(Limits)))) {
                Stop();
                throw new InvalidOperationException("Windows не смогла создать управляемый процесс Codex.");
            }
        }
        public void Attach(Process process) {
            if (!AssignProcessToJobObject(handle, process.Handle))
                throw new InvalidOperationException("Windows не смогла подключить кнопку остановки Codex.");
        }
        public void Stop() {
            IntPtr value = Interlocked.Exchange(ref handle, IntPtr.Zero);
            if (value != IntPtr.Zero) CloseHandle(value);
        }
        public void Dispose() { Stop(); }
    }
}
