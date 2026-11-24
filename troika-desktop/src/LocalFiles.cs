using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace Troika.Desktop {
    public sealed class LocalFileRequest {
        public readonly string Action, Target;
        private LocalFileRequest(string action, string target) { Action = action; Target = target; }
        private static readonly Regex[] Patterns = {
            new Regex(@"^(?:покажи\s+(?:(?:содержимое|файлы)(?:\s+в)?\s+)?папк[уеаи]|что\s+в\s+папке|посмотри(?:,?\s+что)?\s+в\s+папке|покажи\s+файлы\s+на\s+(?:пк|компьютере))(?:\s+(.*))?$", RegexOptions.IgnoreCase),
            new Regex(@"^открой\s+(?:папку|каталог)(?:\s+(.*))?$", RegexOptions.IgnoreCase),
            new Regex(@"^(?:открой|покажи)\s+(?:локальный\s+)?файл\s+(.+)$", RegexOptions.IgnoreCase),
            new Regex(@"^(?:прочитай|просмотри|посмотри)\s+(?:текст\s+из\s+)?(?:локальный\s+)?файл\s+(.+)$", RegexOptions.IgnoreCase),
            new Regex(@"^найди\s+(?:локальный\s+)?файл\s+(.+)$", RegexOptions.IgnoreCase),
            new Regex(@"^создай\s+папку\s+(.+)$", RegexOptions.IgnoreCase)
        };
        private static readonly string[] Actions = { "list", "folder", "open", "read", "find", "create" };
        public static LocalFileRequest Parse(string input) {
            string value = input.Trim().TrimEnd('!', '?');
            if (value.StartsWith("Тройка,", StringComparison.OrdinalIgnoreCase)) value = value.Substring(7).TrimStart();
            for (int i = 0; i < Patterns.Length; i++) {
                var match = Patterns[i].Match(value);
                if (match.Success) return new LocalFileRequest(Actions[i], match.Groups[1].Value.Trim().TrimEnd('.').Trim('"', '«', '»'));
            }
            return null;
        }
    }

    public static class LocalFileAccess {
        public static string Resolve(string root, string name) {
            root = ValidateRoot(root);
            if (string.IsNullOrWhiteSpace(name) || name.Equals(Path.GetFileName(root), StringComparison.OrdinalIgnoreCase)
                || (root.EndsWith("\\Downloads", StringComparison.OrdinalIgnoreCase) && Regex.IsMatch(name, "^загрузк[аи]х?$", RegexOptions.IgnoreCase)))
                return root;
            var path = name.Replace('/', '\\');
            if (Path.IsPathRooted(path)) {
                if (path.Equals(root, StringComparison.OrdinalIgnoreCase)) return root;
                if (!path.StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Путь находится за пределами выбранной папки.");
                path = path.Substring(root.Length + 1);
            }
            string current = root;
            foreach (string part in path.Split('\\')) {
                current = Path.Combine(current, LocalStore.SafeName(part));
                RejectLinks(current);
            }
            return current;
        }
        public static string ValidateRoot(string root) {
            if (string.IsNullOrWhiteSpace(root)) throw new InvalidOperationException("Сначала выберите рабочую папку.");
            var path = Path.GetFullPath(root).TrimEnd('\\');
            if (path.Length <= 3 || !Regex.IsMatch(path, @"^[A-Za-z]:\\") || new DriveInfo(Path.GetPathRoot(path)).DriveType == DriveType.Network || !Directory.Exists(path))
                throw new InvalidOperationException("Выберите локальную папку внутри диска Windows.");
            for (var entry = new DirectoryInfo(path); entry != null; entry = entry.Parent) RejectLinks(entry.FullName);
            return path;
        }
        private static void RejectLinks(string path) {
            try {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("Папки и файлы-ссылки недоступны.");
            } catch (FileNotFoundException) { } catch (DirectoryNotFoundException) { }
        }
        public static IEnumerable<string> Entries(string folder) {
            foreach (var path in Directory.EnumerateFileSystemEntries(folder).Take(4000)) {
                FileAttributes attributes;
                try { attributes = File.GetAttributes(path); }
                catch (IOException) { continue; }
                catch (UnauthorizedAccessException) { continue; }
                if ((attributes & (FileAttributes.ReparsePoint | FileAttributes.Hidden | FileAttributes.System)) == 0) yield return path;
            }
        }
        public static List<string> Find(string root, string name, bool exact = false) {
            root = ValidateRoot(root);
            if (name.Length == 0 || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                throw new InvalidOperationException("Укажите имя файла или часть имени.");
            var matches = new List<string>();
            var pending = new Queue<Tuple<string, int>>();
            pending.Enqueue(Tuple.Create(root, 0));
            int scanned = 0;
            while (pending.Count > 0 && scanned < 5000 && matches.Count < 20) {
                var next = pending.Dequeue();
                try {
                    foreach (var entry in Entries(next.Item1)) {
                        if (++scanned > 5000 || matches.Count >= 20) break;
                        if (Directory.Exists(entry)) {
                            if (next.Item2 < 5) pending.Enqueue(Tuple.Create(entry, next.Item2 + 1));
                        } else {
                            var filename = Path.GetFileName(entry);
                            if (exact ? filename.Equals(name, StringComparison.OrdinalIgnoreCase) : filename.IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0)
                                matches.Add(entry);
                        }
                    }
                } catch (UnauthorizedAccessException) { } catch (DirectoryNotFoundException) { }
            }
            return matches;
        }
        public static string ReadPreview(string path) {
            if (!new[] { ".txt", ".md", ".csv", ".tsv", ".json", ".log" }.Contains(Path.GetExtension(path).ToLowerInvariant()))
                throw new InvalidOperationException("Чтение доступно для TXT, Markdown, CSV, TSV, JSON и LOG. Другие форматы можно открыть в Windows.");
            var text = new char[8001]; int count;
            using (var reader = new StreamReader(path, Encoding.UTF8, true))
                count = reader.ReadBlock(text, 0, text.Length);
            return new string(text, 0, Math.Min(count, 8000)) + (count > 8000 ? "\n\nПоказано начало файла." : "");
        }
    }

    public sealed partial class MainWindow {
        private string LocalFilePreference() {
            return Path.Combine(store.FilesFolder(api.Account.Email), ".local-work-folder.txt");
        }
        private string LocalFileRoot() {
            if (!api.Account.SignedIn) return "";
            try { return File.ReadAllText(LocalFilePreference()); }
            catch (IOException) { return ""; }
        }
        private void RenderLocalFiles() {
            panelContent.Children.Clear();
            panelContent.Children.Add(Label("Рабочая папка на ПК", 20, text));
            if (!api.Account.SignedIn) {
                AddPanelButton("Войдите, чтобы выбрать папку", () => OpenPanel("Аккаунт"), true);
                return;
            }
            var root = LocalFileRoot();
            panelContent.Children.Add(Label(root.Length == 0 ? "Выберите папку, чтобы Тройка могла просматривать её по голосовой команде." : root, 13, muted));
            AddPanelButton("Выбрать папку…", () => {
                using (var picker = new System.Windows.Forms.FolderBrowserDialog { Description = "Выберите рабочую папку на ПК" }) {
                    if (picker.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;
                    try {
                        string path = LocalFileAccess.ValidateRoot(picker.SelectedPath);
                        LocalStore.WriteAtomic(LocalFilePreference(), Encoding.UTF8.GetBytes(path));
                        RenderLocalFiles();
                    } catch (Exception error) { SetStatus(error.Message, true); }
                }
            }, true);
            if (root.Length > 0) {
                AddPanelButton("Открыть папку в Проводнике", () => {
                    try { Process.Start(new ProcessStartInfo(LocalFileAccess.ValidateRoot(root)) { UseShellExecute = true }); }
                    catch (Exception error) { SetStatus(error.Message, true); }
                }, false);
                AddPanelButton("Убрать доступ к папке", () => {
                    File.Delete(LocalFilePreference()); RenderLocalFiles();
                }, false);
            }
            panelContent.Children.Add(Label("Скажите «Покажи содержимое папки», «Найди файл отчёт» или «Прочитай файл заметки.txt».", 13, muted));
        }
        private async Task HandleLocalFileRequest(string input, LocalFileRequest request) {
            var root = LocalFileRoot();
            if (root.Length == 0) {
                ShowFromTray();
                await OpenPanelTask("Рабочая папка");
                SetStatus("Сначала выберите рабочую папку на ПК.", false);
                return;
            }
            string owner = api.Account.Email;
            AddMessage("user", input);
            try {
                string target = request.Target;
                if (request.Action == "open" || request.Action == "read")
                    target = Regex.Replace(target, @"\s+точка\s+", ".", RegexOptions.IgnoreCase);
                var result = await Task.Run(() => RunLocalFileRequest(root, target, request.Action));
                if (closed || !api.Account.SignedIn || api.Account.Email != owner || LocalFileRoot() != root) return;
                if (result.Item2.Length > 0) {
                    var path = LocalFileAccess.Resolve(root, result.Item2);
                    if (Directory.Exists(path)) Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
                    else if (!OpenableLocalFile(path)) throw new InvalidOperationException("Для этого формата откройте файл вручную через Проводник.");
                    else Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
                }
                var message = AddMessage("assistant", "");
                message.Text = result.Item1; message.Tag = result.Item1;
                SetStatus("Готово на этом ПК", false);
                if (autoSpeak && !busy && !speaking && !recorder.Recording && !wakeRecording)
                    await Safe(() => Speak("Готово. Подробности в окне Тройки.", System.Threading.CancellationToken.None));
            } catch (Exception error) {
                if (closed || api.Account.Email != owner) return;
                AddMessage("assistant", error.Message);
                SetStatus(error.Message, true);
            }
        }
        private static bool OpenableLocalFile(string path) {
            return new[] { ".docx", ".pptx", ".xlsx", ".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".zip", ".csv" }.Contains(Path.GetExtension(path).ToLowerInvariant());
        }
        private static Tuple<string, string> RunLocalFileRequest(string root, string target, string action) {
            root = LocalFileAccess.ValidateRoot(root);
            if (action == "find") {
                var matches = LocalFileAccess.Find(root, target);
                return Tuple.Create(matches.Count == 0 ? "Файлы с таким именем не найдены." : string.Join("\n", matches.Select(path => path.Substring(root.Length + 1))), "");
            }
            if (action == "create") {
                var created = LocalFileAccess.Resolve(root, LocalStore.SafeName(target));
                Directory.CreateDirectory(created);
                return Tuple.Create("Папка готова: " + Path.GetFileName(created), "");
            }
            var pathAtRoot = LocalFileAccess.Resolve(root, target);
            if (action == "list" || action == "folder") {
                if (!Directory.Exists(pathAtRoot)) throw new DirectoryNotFoundException("Папка не найдена внутри выбранной рабочей папки.");
                if (action == "folder") return Tuple.Create("Папка открыта на этом ПК.", pathAtRoot);
                var rows = LocalFileAccess.Entries(pathAtRoot).Take(41).ToList();
                var list = rows.Count == 0 ? "В папке нет доступных файлов." : string.Join("\n", rows.Take(40).Select(path => Path.GetFileName(path) + (Directory.Exists(path) ? "\\" : "")));
                return Tuple.Create(list + (rows.Count > 40 ? "\nПоказаны первые 40 элементов." : ""), "");
            }
            if (!File.Exists(pathAtRoot) && target.IndexOfAny(new[] { '\\', '/', ':' }) < 0) {
                var matches = LocalFileAccess.Find(root, target, true);
                if (matches.Count > 1) throw new InvalidOperationException("Есть несколько файлов с таким именем. Укажите путь внутри рабочей папки.");
                if (matches.Count == 1) pathAtRoot = LocalFileAccess.Resolve(root, matches[0]);
            }
            if (!File.Exists(pathAtRoot)) throw new FileNotFoundException("Файл не найден внутри выбранной рабочей папки.");
            return action == "open" ? Tuple.Create("Файл открыт на этом ПК.", pathAtRoot)
                : Tuple.Create(Path.GetFileName(pathAtRoot) + "\n\n" + LocalFileAccess.ReadPreview(pathAtRoot), "");
        }
    }
}
