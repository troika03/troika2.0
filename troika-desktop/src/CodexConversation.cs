using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace Troika.Desktop {
    public static class CodexDevelopmentIntent {
        private const RegexOptions Options = RegexOptions.IgnoreCase | RegexOptions.CultureInvariant;
        private const string Request = @"^(?:тройка[\s,:]+)?(?:(?:давай|пожалуйста|можешь|можно)\s+)*";
        private const string Build = @"(?:созда(?:й|ть)|сдела(?:й|ть)|напиши|написать|сверста(?:й|ть)|собери|собрать|разработа(?:й|ть)|реализуй|реализовать|запрограммируй)";
        private static readonly Regex NewProject = new Regex(Request + Build + @"\s+(?:\w+\s+){0,3}нов(?:ый|ую|ое)\s+(?:проект|сайт|приложение|игру|бота)\b", Options);
        private static readonly Regex Creation = new Regex(Request + Build + @"\s+(?:(?:мне|нам|полноценн\w+|нов\w+|небольш\w+|прост\w+|тестов\w+|готов\w+|демо|веб)\s+){0,4}(?:проект|сайт|лендинг|веб[- ]приложение|приложение|игру|бота|скрипт|код|api|расширение|микросервис)\b", Options);
        private static readonly Regex Edit = new Regex(Request + @"(?:добавь|добавить|исправь|исправить|почини|починить|проверь|проверить|обнови|обновить|измени|изменить|переделай|доработай|убери|замени|переименуй|запусти|продолжи|продолжим|сделай|перенеси|улучши|напиши|напишем)\b", Options);
        private static readonly Regex ExistingProject = new Regex(@"\b(?:проект\w*|репозитори\w+|сайт\w*|лендинг\w*|приложени\w+|фронтенд\w*|бэкенд\w*|readme|css|html|javascript|typescript|react|pytest)\b", Options);
        private static readonly Regex ProjectContext = new Regex(@"\b(?:проект\w*|репозитори\w+|код\w*|тест\w*|сборк\w+|баг\w*|фронтенд\w*|бэкенд\w*|сайт\w*|лендинг\w*|приложени\w+|компонент\w*|интерфейс\w*|кнопк\w+|форм[аеуы]\b|авторизаци\w+|api|readme|css|html|javascript|python|typescript|react|npm|pytest)\b", Options);
        private static readonly Regex Unrelated = new Regex(Request + @"(?:проверь\s+(?:погод\w+|почт\w+|новост\w+)|(?:создай|напиши|сделай|добавь|запусти)\s+(?:мне\s+)?(?:презентаци\w+|письм\w+|доклад\w*|документ\w*|отч[её]т\w*|напоминани\w+|заметк\w+|музык\w+|калькулятор|блокнот|приложение\s+к\s+договору)\b)", Options);

        public static string Match(string input, bool hasProject) {
            if (Unrelated.IsMatch(input)) return "";
            if (NewProject.IsMatch(input)) return "new";
            if (Creation.IsMatch(input)) return hasProject ? "continue" : "new";
            if (!Edit.IsMatch(input)) return "";
            if (hasProject && ProjectContext.IsMatch(input)) return "continue";
            if (!hasProject && ExistingProject.IsMatch(input)) return "new";
            return "";
        }
    }

    public sealed class CodexConversationLink {
        public readonly string Conversation, Folder, Thread;
        public CodexConversationLink(string conversation, string folder, string thread = "") {
            if (string.IsNullOrWhiteSpace(conversation) || conversation.Length > 256)
                throw new ArgumentException("Не удалось определить разговор Тройки.");
            if (!Path.IsPathRooted(folder)) throw new ArgumentException("Требуется полный путь к папке проекта.");
            Conversation = conversation;
            Folder = Path.GetFullPath(folder);
            Thread = thread.Length == 0 ? "" : NormalizeThread(thread);
        }
        public static string NormalizeThread(string value) {
            Guid id;
            if (!Guid.TryParseExact(value, "D", out id) || id == Guid.Empty)
                throw new InvalidDataException("Codex вернул некорректный идентификатор чата.");
            return id.ToString("D");
        }
        public static string ThreadUrl(string value) { return "codex://threads/" + NormalizeThread(value); }
        public CodexConversationLink WithThread(string value) { return new CodexConversationLink(Conversation, Folder, value); }
    }

    public sealed class CodexConversationStore {
        private readonly string directory;
        private readonly byte[] entropy;
        public CodexConversationStore(LocalStore store, string owner) {
            directory = Path.Combine(store.FilesFolder(owner), ".codex-conversations");
            entropy = Encoding.UTF8.GetBytes("Troika Codex " + owner.ToLowerInvariant());
        }
        private string FileFor(string conversation) {
            return Path.Combine(directory, LocalStore.Hash(Encoding.UTF8.GetBytes(conversation)) + ".dat");
        }
        public CodexConversationLink Read(string conversation) {
            if (string.IsNullOrWhiteSpace(conversation)) return null;
            var link = ReadFile(FileFor(conversation));
            return link != null && link.Conversation == conversation ? link : null;
        }
        public IEnumerable<CodexConversationLink> Recent() {
            if (!Directory.Exists(directory)) yield break;
            FileInfo[] files;
            try { files = new DirectoryInfo(directory).GetFiles("*.dat"); }
            catch (IOException) { yield break; }
            catch (UnauthorizedAccessException) { yield break; }
            foreach (var file in files.OrderByDescending(item => item.LastWriteTimeUtc).Take(30)) {
                var value = ReadFile(file.FullName);
                if (value != null && FileFor(value.Conversation).Equals(file.FullName, StringComparison.OrdinalIgnoreCase)) yield return value;
            }
        }
        private CodexConversationLink ReadFile(string file) {
            try {
                var info = new FileInfo(file);
                if (!info.Exists || info.Length > 16384 || (info.Attributes & FileAttributes.ReparsePoint) != 0) return null;
                var data = ProtectedData.Unprotect(File.ReadAllBytes(file), entropy, DataProtectionScope.CurrentUser);
                try {
                    var value = Json.Parse(Encoding.UTF8.GetString(data));
                    return new CodexConversationLink(Json.Text(value, "conversation"), Json.Text(value, "folder"), Json.Text(value, "thread"));
                } finally { Array.Clear(data, 0, data.Length); }
            } catch (IOException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
            catch (CryptographicException) { return null; }
            catch (ArgumentException) { return null; }
        }
        public void Save(CodexConversationLink link) {
            var data = Encoding.UTF8.GetBytes(Json.Encode(new { conversation = link.Conversation, folder = link.Folder, thread = link.Thread }));
            try { LocalStore.WriteAtomic(FileFor(link.Conversation), ProtectedData.Protect(data, entropy, DataProtectionScope.CurrentUser)); }
            finally { Array.Clear(data, 0, data.Length); }
        }
        public void Forget(string conversation) { if (!string.IsNullOrEmpty(conversation)) File.Delete(FileFor(conversation)); }
    }
}
