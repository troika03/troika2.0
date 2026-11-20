using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    public sealed class CheckReport {
        public string Output = "", Kind = "";
        public int ExitCode = -1;
        public bool Verified;
        public bool Stopped;
        public bool TimedOut;
        public bool NoTests;
    }
    public static class Development {
        private static readonly HashSet<string> Extensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".css",
            ".html", ".htm", ".yaml", ".yml", ".toml", ".csv", ".dart", ".cs", ".xml", ".java",
            ".kt", ".cpp", ".hpp", ".c", ".h", ".go", ".rs", ".swift", ".vue", ".svelte"
        };
        private static bool HasHiddenComponent(string name) {
            var parts = name.Split('/');
            for (int i = 0; i < parts.Length; i++) {
                if (parts[i].StartsWith(".") && !(i == parts.Length - 1 && parts[i] == ".gitignore")) return true;
            }
            return false;
        }
        private static bool IsSourceFile(string name) {
            var filename = Path.GetFileName(name);
            return filename == ".gitignore" || filename == "go.mod" || filename == "go.sum" ||
                filename == "Cargo.lock" || Extensions.Contains(Path.GetExtension(name));
        }
        public static string Extract(string archive, string projectsRoot) {
            var root = Path.GetFullPath(projectsRoot); Directory.CreateDirectory(root);
            if ((File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Папка проектов не должна быть ссылкой.");
            var destination = Path.Combine(root, "project-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            Directory.CreateDirectory(destination);
            try {
                long total = 0; int count = 0;
                using (var zip = ZipFile.OpenRead(archive)) {
                    foreach (var entry in zip.Entries) {
                        if (++count > 300) throw new InvalidDataException("В проекте больше 300 файлов.");
                        var name = entry.FullName.Replace('\\', '/');
                        var segments = name.Split('/');
                        if (name.StartsWith("/") || HasHiddenComponent(name) || segments.Any(s => s.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0) || ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000) throw new InvalidDataException("ZIP содержит небезопасный путь или ссылку.");
                        var path = Path.GetFullPath(Path.Combine(destination, name));
                        if (!path.StartsWith(destination + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Путь выходит за папку проекта.");
                        if (name.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
                        LocalStore.SafeName(Path.GetFileName(path));
                        if (!IsSourceFile(name)) throw new InvalidDataException("В ZIP разрешены только исходники и текстовые файлы.");
                        if (entry.Length > 1024 * 1024 || (total += entry.Length) > 10 * 1024 * 1024) throw new InvalidDataException("Проект слишком большой.");
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using (var input = entry.Open()) using (var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                            var buffer = new byte[8192]; int read; long actual = 0;
                            while ((read = input.Read(buffer, 0, buffer.Length)) > 0) { actual += read; if (actual > entry.Length || actual > 1024 * 1024) throw new InvalidDataException("Размер файла не совпадает с ZIP."); output.Write(buffer, 0, read); }
                            output.Flush(true);
                        }
                    }
                }
                if (!Directory.EnumerateFiles(destination, "*", SearchOption.AllDirectories).Any()) throw new InvalidDataException("ZIP не содержит исходников.");
                return destination;
            } catch { Directory.Delete(destination, true); throw; }
        }
        public static string Interpreter(string executable) {
            foreach (var folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator)) {
                if (string.IsNullOrWhiteSpace(folder)) continue;
                try { var path = Path.GetFullPath(Path.Combine(folder.Trim('"'), executable)); if (File.Exists(path) && !path.EndsWith("WindowsApps\\" + executable, StringComparison.OrdinalIgnoreCase)) return path; } catch { }
            }
            throw new FileNotFoundException("Установите " + (executable.StartsWith("python") ? "Python" : "Node.js") + " и добавьте его в PATH.");
        }
        public static async Task<CheckReport> Check(string folder, string kind, CancellationToken cancellation) {
            folder = Path.GetFullPath(folder);
            if (!Directory.Exists(folder) || (File.GetAttributes(folder) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Папка проекта недоступна.");
            RejectLinks(folder);
            var files = Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories).Where(f => Path.GetFileName(f) != "check-report.txt" && !f.Contains(Path.DirectorySeparatorChar + "__pycache__" + Path.DirectorySeparatorChar)).ToList();
            if (files.Any(f => (File.GetAttributes(f) & FileAttributes.ReparsePoint) != 0)) throw new InvalidDataException("Файлы проекта не должны быть ссылками.");
            var report = new CheckReport { Kind = kind };
            string interpreter; List<string> arguments = new List<string>();
            if (kind == "Python: тесты") { interpreter = Interpreter("python.exe"); arguments.Add("-I -B -m unittest discover -s \"" + folder + "\""); }
            else if (kind == "JavaScript: тесты") {
                interpreter = Interpreter("node.exe");
                var tests = files.Where(f => f.EndsWith(".test.js", StringComparison.OrdinalIgnoreCase) || Path.GetFileName(f).StartsWith("test_") && f.EndsWith(".js", StringComparison.OrdinalIgnoreCase)).ToList();
                if (tests.Count == 0) { report.NoTests = true; report.Output = "Тесты не найдены."; return report; }
                arguments.Add("--test " + string.Join(" ", tests.Select(f => "\"" + f + "\"")));
            } else {
                string extension = kind == "Python: синтаксис" ? ".py" : ".js";
                interpreter = Interpreter(extension == ".py" ? "python.exe" : "node.exe");
                foreach (var file in files.Where(f => Path.GetExtension(f).ToLowerInvariant() == extension)) arguments.Add((extension == ".py" ? "-I -B -c \"import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8-sig').read(), filename=sys.argv[1])\" " : "--check ") + "\"" + file + "\"");
                if (arguments.Count == 0) { report.Output = "Нет файлов для выбранной проверки. Проверка не выполнена."; return report; }
            }
            var output = new StringBuilder(); int exit = 0;
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation)) {
                deadline.CancelAfter(TimeSpan.FromSeconds(90));
                foreach (var argument in arguments) {
                    var start = new ProcessStartInfo(interpreter, argument) { WorkingDirectory = folder, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
                    var environment = new Dictionary<string, string>();
                    foreach (var key in new[] { "PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT" }) { var value = Environment.GetEnvironmentVariable(key); if (value != null) environment[key] = value; }
                    start.EnvironmentVariables.Clear(); foreach (var item in environment) start.EnvironmentVariables[item.Key] = item.Value;
                    start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"; start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
                    using (var job = new ProcessJob())
                    using (var process = new Process { StartInfo = start }) {
                        process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs ev) { if (ev.Data != null) lock (output) { if (output.Length < 64000) output.AppendLine(ev.Data); } };
                        process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs ev) { if (ev.Data != null) lock (output) { if (output.Length < 64000) output.AppendLine(ev.Data); } };
                        cancellation.ThrowIfCancellationRequested(); process.Start();
                        if (!job.Assign(process)) { process.Kill(); throw new InvalidOperationException("Windows не создала группу для остановки проверки. Запуск прерван."); }
                        process.BeginOutputReadLine(); process.BeginErrorReadLine();
                        while (!process.HasExited && !deadline.IsCancellationRequested) await Task.Delay(100);
                        if (!process.HasExited) { job.Dispose(); await Task.Run(() => process.WaitForExit()); report.Stopped = true; report.TimedOut = !cancellation.IsCancellationRequested; output.AppendLine("Проверка остановлена или истекли 90 секунд."); exit = -1; break; }
                        await Task.Run(() => process.WaitForExit()); exit = process.ExitCode;
                    }
                    if (exit != 0) break;
                }
            }
            report.ExitCode = exit; report.Output = output.ToString();
            report.NoTests = kind == "Python: тесты" && !Regex.IsMatch(report.Output, @"Ran [1-9][0-9]* tests?") || kind == "JavaScript: тесты" && !Regex.IsMatch(report.Output, @"# tests [1-9][0-9]*");
            report.Verified = exit == 0 && !report.Stopped && !report.NoTests;
            if (exit == 0 && !report.Verified) report.Output += "\nНулевое число тестов не подтверждает качество проекта.";
            if (report.Output.Length == 0) report.Output = report.Verified ? "Проверка синтаксиса выполнена. Программа и её поведение не проверялись." : "Нет результата проверки.";
            return report;
        }
        public static string RepairContext(string folder, CheckReport report) {
            if (report == null) throw new InvalidOperationException("Сначала выполните проверку проекта.");
            var context = new StringBuilder("Исправь проект по отчёту локальной проверки. Верни новую версию проекта ZIP с исходниками, README и тестами. Не утверждай, что тесты запускались на сервере.\nОтчёт:\n" + Redact(report.Output) + "\nИсходники:\n");
            int count = 0;
            foreach (var file in Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories)) {
                var name = file.Substring(folder.Length).TrimStart(Path.DirectorySeparatorChar).Replace('\\', '/');
                if (!IsSourceFile(name) || HasHiddenComponent(name) || file.Contains(Path.DirectorySeparatorChar + "__pycache__" + Path.DirectorySeparatorChar) || new FileInfo(file).Length > 100000) continue;
                if (++count > 100) throw new InvalidDataException("Больше 100 исходных файлов. Уменьшите проект.");
                var source = File.ReadAllText(file);
                if (Regex.IsMatch(source, @"trk_(live|refresh)_|(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['""].+?['""]")) throw new InvalidDataException("В исходниках найдены возможные секреты. Удалите их перед отправкой.");
                context.AppendLine(file.Substring(folder.Length).TrimStart(Path.DirectorySeparatorChar)).AppendLine(source);
                if (context.Length > 150000) throw new InvalidDataException("Исходники слишком большие для безопасной передачи.");
            }
            return context.ToString();
        }
        public static Dictionary<string, string> Sources(string folder) {
            folder = Path.GetFullPath(folder); var result = new Dictionary<string, string>(); int bytes = 0;
            RejectLinks(folder);
            foreach (var file in Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories)) {
                if (file.Contains(Path.DirectorySeparatorChar + "__pycache__" + Path.DirectorySeparatorChar) || Path.GetFileName(file) == "check-report.txt") continue;
                if ((File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Файл является ссылкой.");
                var name = file.Substring(folder.Length).TrimStart(Path.DirectorySeparatorChar).Replace('\\', '/');
                ValidateSource(name, File.ReadAllText(file)); var content = File.ReadAllText(file); bytes += Encoding.UTF8.GetByteCount(content);
                if (bytes > 2*1024*1024 || result.Count >= 96) throw new InvalidDataException("Проект больше 2 МБ или 96 исходных файлов."); result.Add(name, content);
            }
            return result;
        }
        private static void RejectLinks(string folder) {
            var pending = new Stack<string>(); pending.Push(folder);
            while (pending.Count > 0) { var current = pending.Pop(); if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Папка проекта является ссылкой."); foreach (var directory in Directory.EnumerateDirectories(current)) pending.Push(directory); }
        }
        public static void ValidateSource(string name, string content) {
            if (string.IsNullOrEmpty(name) || name.Contains('\\') || name.Split('/').Any(p => p.Length == 0) || HasHiddenComponent(name) || !IsSourceFile(name)) throw new InvalidDataException("Недопустимый путь исходника.");
            foreach (var part in name.Split('/')) LocalStore.SafeName(part);
            if (Regex.IsMatch(content, @"trk_(live|refresh)_|sk-[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY|(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['""].+?['""]")) throw new InvalidDataException("В исходниках найдены возможные секреты.");
        }
        public static string Kind(string mode) {
            switch (mode) { case "python_tests": return "Python: тесты"; case "python_syntax": return "Python: синтаксис"; case "javascript_tests": return "JavaScript: тесты"; case "javascript": return "JavaScript: синтаксис"; default: throw new InvalidDataException("Неизвестная проверка."); }
        }
        public static string Mode(string kind) { switch (kind) { case "Python: тесты": return "python_tests"; case "Python: синтаксис": return "python_syntax"; case "JavaScript: тесты": return "javascript_tests"; case "JavaScript: синтаксис": return "javascript"; default: throw new InvalidDataException("Неизвестная проверка."); } }
        private static string Redact(string text) { return Regex.Replace(text, @"trk_(live|refresh)_[A-Za-z0-9_-]+|(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+", "[скрыто]"); }
    }
    internal sealed class ProcessJob : IDisposable {
        [StructLayout(LayoutKind.Sequential)] struct BasicLimits { public long ProcessTime, JobTime; public uint Flags; public UIntPtr Minimum, Maximum; public uint ActiveProcesses; public UIntPtr Affinity; public uint Priority, Scheduling; }
        [StructLayout(LayoutKind.Sequential)] struct Counters { public ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes; }
        [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits { public BasicLimits Basic; public Counters IO; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory; }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int kind, IntPtr info, uint length);
        [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
        private IntPtr handle;
        public ProcessJob() {
            handle = CreateJobObject(IntPtr.Zero, null); if (handle == IntPtr.Zero) throw new InvalidOperationException("Не удалось создать группу проверки.");
            var limits = new ExtendedLimits { Basic = new BasicLimits { Flags = 0x2000 } }; var length = Marshal.SizeOf(typeof(ExtendedLimits)); var memory = Marshal.AllocHGlobal(length);
            try { Marshal.StructureToPtr(limits, memory, false); if (!SetInformationJobObject(handle, 9, memory, (uint)length)) { Dispose(); throw new InvalidOperationException("Не удалось ограничить время жизни проверки."); } } finally { Marshal.FreeHGlobal(memory); }
        }
        public bool Assign(Process process) { return AssignProcessToJobObject(handle, process.Handle); }
        public void Dispose() { if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; } }
    }
}
