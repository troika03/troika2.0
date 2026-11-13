using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Runtime.ExceptionServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    internal sealed class ComputerUseDeviceOptions {
        internal string Permission, Project, Entry, SecondEntry;
        internal string[] Apps;
        internal bool Mobile, ShareHeadings;
    }

    internal sealed class ComputerUseDeviceRun : IDisposable {
        private readonly string workspace, python, address, token;
        private readonly ApiClient api;

        internal ComputerUseDeviceRun(string workspace, string address, string token, HttpMessageHandler handler = null) {
            this.address = ComputerUseAgent.LoopbackOrigin(address).AbsoluteUri;
            this.workspace = Path.GetFullPath(workspace);
            python = Path.Combine(this.workspace, @".venv\Scripts\python.exe");
            if (!File.Exists(python) || !File.Exists(Path.Combine(this.workspace, @"scripts\troika_windows_browser_lab.py")))
                throw new ArgumentException("Укажите папку разработки Тройки с подготовленным Python.");
            api = ComputerUseConsentWindow.Connect(address, token, handler);
            this.token = token;
        }

        internal async Task<string> ExecuteAsync(string goal, ComputerUseDeviceOptions options,
                Func<string, string, string, TimeSpan, Task<bool>> approve, Action<string> progress, CancellationToken cancellation) {
            if (!ComputerUseAgent.ValidGoal(goal) || !new[] { "ask", "run", "view" }.Contains(options.Permission))
                throw new ArgumentException("Нужны задача и режим разрешений.");
            string runId = null, output = null;
            Exception failure = null;
            try {
                var devices = await Call("GET", "/v1/account/devices", null, cancellation);
                var current = Json.Rows(devices, "devices").SingleOrDefault(item => Json.Flag(item, "current"));
                string device = current == null ? "" : Json.Text(current, "id");
                if (device.Length == 0 || device.Length > 64 || Json.Text(current, "platform") != "windows"
                        || Json.Text(current, "status") != "active")
                    throw new InvalidOperationException("Тестовый токен не принадлежит активному устройству Windows.");
                cancellation.ThrowIfCancellationRequested();

                // Wait for the Run identifier even if Stop arrives during the request.
                var run = await Call("POST", "/v1/runs", new { input = goal, computer_use = true },
                    CancellationToken.None, 25);
                string requested = Json.Text(run, "run_id");
                if (!Regex.IsMatch(requested, @"\Arun_[a-f0-9]{32}\z")) throw new InvalidDataException();
                runId = requested;
                cancellation.ThrowIfCancellationRequested();
                var grant = await Call("POST", "/v1/runs/" + runId + "/computer-windows-browser/request",
                    new { version = 1, target_device_id = device, ttl_seconds = ComputerUseSession.ConsentSeconds }, cancellation);
                string grantId = Json.Text(grant, "grant_id");
                if (!Regex.IsMatch(grantId, @"\A[a-f0-9]{32}\z") || Json.Text(grant, "mode") != "windows_browser_lab"
                        || Json.Text(grant, "status") != "pending" || Json.Text(grant, "target_device_id") != device)
                    throw new InvalidDataException();
                string saved = await RunWorker(runId, grantId, options, approve, progress, cancellation);
                var status = await Call("GET", "/v1/runs/" + runId, null, cancellation);
                string result = Json.Text(status, "output");
                string errorCode = Json.Text(status, "error_code");
                if (Json.Text(status, "status") == "failed"
                        && errorCode.StartsWith("openrouter_", StringComparison.Ordinal)) {
                    result = errorCode == "openrouter_rate_limited" ? "OpenRouter ограничил частоту запросов. Задача прервана."
                        : errorCode == "openrouter_timeout" ? "Время ожидания OpenRouter истекло. Задача прервана."
                        : "OpenRouter прервал задачу.";
                } else if (Json.Text(status, "status") != "completed" || !ComputerUseAgent.ValidGoal(result)) {
                    throw new InvalidOperationException("Сервер не подтвердил завершение задачи.");
                }
                output = saved == null ? result : result + "\n" + saved;
            } catch (Exception error) { failure = error; }
            if (failure == null) return output;

            bool revoked = runId == null || await Revoke(runId);
            if (cancellation.IsCancellationRequested)
                return revoked ? "Остановлено." : "Остановлено на этом ПК. Сервер не подтвердил остановку.";
            ExceptionDispatchInfo.Capture(failure).Throw();
            return null;
        }

        private async Task<string> RunWorker(string runId, string grantId, ComputerUseDeviceOptions options,
                Func<string, string, string, TimeSpan, Task<bool>> approve, Action<string> progress, CancellationToken cancellation) {
            var start = new ProcessStartInfo(python, "-E -s -B -u -X utf8 -m scripts.troika_windows_browser_lab"
                    + " --desktop-bridge --show --run " + address + " " + runId + " " + grantId + " --permission " + options.Permission) {
                WorkingDirectory = workspace, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            start.EnvironmentVariables.Clear();
            foreach (string name in new[] { "SystemRoot", "WINDIR", "SystemDrive", "LOCALAPPDATA", "APPDATA", "ProgramData",
                    "USERPROFILE", "ProgramFiles", "ProgramFiles(x86)", "TEMP", "TMP", "PATH", "COMSPEC" }) {
                string value = Environment.GetEnvironmentVariable(name);
                if (value != null) start.EnvironmentVariables[name] = value;
            }
            start.EnvironmentVariables["TROIKA_COMPUTER_TEST_DEVICE_TOKEN"] = token;
            using (var notepad = new ComputerUseNotepadControl())
            using (var job = new ProcessJob())
            using (var process = new Process { StartInfo = start }) {
                cancellation.ThrowIfCancellationRequested();
                if (!process.Start()) throw new InvalidOperationException("Не удалось запустить управление приложениями.");
                if (!job.Assign(process)) {
                    if (!process.HasExited) process.Kill();
                    throw new InvalidOperationException("Не удалось запустить управление приложениями с остановкой.");
                }
                process.ErrorDataReceived += (sender, args) => { };
                process.BeginErrorReadLine();
                using (var input = new StreamWriter(process.StandardInput.BaseStream, new UTF8Encoding(false), 512, true) { AutoFlush = true }) {
                    cancellation.ThrowIfCancellationRequested();
                    await input.WriteLineAsync(Json.Encode(new { start = true, apps = options.Apps, project = options.Project, entry = options.Entry,
                        second_entry = options.SecondEntry, mobile = options.Mobile, share_headings = options.ShareHeadings }));
                    var stopped = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    using (cancellation.Register(() => stopped.TrySetResult(true))) {
                        var output = ReadWorker(process.StandardOutput, input, options, notepad, approve, progress,
                            async stopToken => Json.Text(await Call("POST", "/v1/runs/" + runId + "/computer-windows-browser/review",
                                new { version = 1, grant_id = grantId }, stopToken), "status") == "active", cancellation);
                        if (await Task.WhenAny(output, stopped.Task) != output) {
                            job.Dispose();
                            try { await output; }
                            catch (IOException) { }
                            catch (OperationCanceledException) { }
                            cancellation.ThrowIfCancellationRequested();
                        }
                        if (!await output || !await Task.Run(() => process.WaitForExit(2000)) || process.ExitCode != 0)
                            throw new InvalidOperationException("Управление ПК завершилось без результата.");
                        return notepad.SavedFile;
                    }
                }
            }
        }

        private static async Task<bool> ReadWorker(StreamReader output, StreamWriter input, ComputerUseDeviceOptions options,
                ComputerUseNotepadControl notepad, Func<string, string, string, TimeSpan, Task<bool>> approve,
                Action<string> progress, Func<CancellationToken, Task<bool>> stillAllowed, CancellationToken cancellation) {
            bool ready = false, finished = false;
            var clock = Stopwatch.StartNew();
            string approvedAction = null, approvedText = null;
            TimeSpan approvalExpires = TimeSpan.Zero;
            string line;
            while ((line = await output.ReadLineAsync()) != null) {
                cancellation.ThrowIfCancellationRequested();
                if (line.Length > 2048 || finished) throw new InvalidDataException();
                var message = Json.Parse(line);
                string kind = Json.Text(message, "kind"), action = Json.Text(message, "action"), app = Json.Text(message, "app");
                if (kind == "ready" && !ready && message.Count == 1) {
                    ready = true;
                    progress("Доступ к выбранным приложениям активен.");
                } else if (kind == "approval" && ready && options.Permission == "ask" && options.Apps.Contains(app)) {
                    TimeSpan remaining = Duration(message);
                    string target;
                    if (app == "browser") {
                        target = BrowserApproval(message, action);
                    } else {
                        approvedAction = approvedText = null;
                        target = NotepadText(message, action, false);
                    }
                    TimeSpan expires = clock.Elapsed + remaining;
                    bool allowed = await approve(app, action, target, remaining);
                    cancellation.ThrowIfCancellationRequested();
                    if (app == "notepad" && allowed) {
                        approvedAction = action;
                        approvedText = target;
                        approvalExpires = expires;
                    }
                    await input.WriteLineAsync(Json.Encode(new { allow = allowed }));
                } else if (kind == "execute" && ready && app == "notepad" && options.Apps.Contains(app)) {
                    string text = NotepadText(message, action, true);
                    TimeSpan remaining = Duration(message);
                    if (action != "inspect") {
                        if (options.Permission == "view") throw new InvalidDataException();
                        if (options.Permission == "ask") {
                            if (approvedAction != action || approvedText != text || clock.Elapsed >= approvalExpires)
                                throw new InvalidDataException();
                            remaining = TimeSpan.FromTicks(Math.Min(remaining.Ticks, (approvalExpires - clock.Elapsed).Ticks));
                            approvedAction = approvedText = null;
                        }
                    }
                    var view = await notepad.Execute(action, text, remaining, stillAllowed, cancellation);
                    cancellation.ThrowIfCancellationRequested();
                    await input.WriteLineAsync(Json.Encode(new { view = view }));
                } else if (kind == "action" && ready && message.Count == 4 && options.Apps.Contains(app)) {
                    string status = Json.Text(message, "status");
                    if (status == "denied") progress("Действие отклонено.");
                    else if (status == "observed" && action == "inspect") progress(app == "browser" ? "Браузер осмотрен." : "Блокнот осмотрен.");
                    else if (status == "verified" && action == "open") progress(app == "browser" ? "Страница открыта." : "Блокнот открыт.");
                    else if (status == "verified" && action == "scroll") progress("Прокрутка подтверждена.");
                    else if (status == "verified" && action == "switch") progress("Переключение окна подтверждено.");
                    else if (status == "verified" && action == "click") progress("Переход к разделу подтверждён.");
                    else if (status == "verified" && action == "write") progress("Текст в Блокноте проверен.");
                    else if (status == "verified" && action == "save") progress("Файл сохранён и проверен.");
                    else if (status == "stale_state") progress("Положение страницы изменилось. Нужен новый осмотр.");
                    else throw new InvalidDataException();
                } else if (kind == "finished" && ready && message.Count == 1) finished = true;
                else if (kind == "failed" && message.Count == 1) return false;
                else throw new InvalidDataException();
            }
            return finished;
        }

        private static string BrowserApproval(Dictionary<string, object> message, string action) {
            if (action == "click") {
                var id = Json.Get(message, "link_id");
                string label = Json.Text(message, "label");
                if (message.Count == 6 && id is int && (int)id >= 1 && (int)id <= 128
                        && !String.IsNullOrWhiteSpace(label) && label.Length <= 256 && !label.Any(Char.IsControl)) return label;
            } else if (message.Count == 5) {
                string target = Json.Text(message, action == "scroll" ? "direction" : "page");
                if (action == "scroll" && (target == "up" || target == "down")) return target;
                if ((action == "open" || action == "switch") && (target == "overview" || target == "details")) return target;
            }
            throw new InvalidDataException();
        }

        private static TimeSpan Duration(Dictionary<string, object> message) {
            object value = Json.Get(message, "remaining_ms");
            if (!(value is int) || (int)value < 1 || (int)value > 30000) throw new InvalidDataException();
            return TimeSpan.FromMilliseconds((int)value);
        }

        private static string NotepadText(Dictionary<string, object> message, string action, bool inspectAllowed) {
            if (action == "write" && message.Count == 5 && ComputerUseExecutor.ValidText(Json.Text(message, "text")))
                return Json.Text(message, "text");
            if (message.Count == 4 && (action == "open" || action == "save" || inspectAllowed && action == "inspect"))
                return null;
            throw new InvalidDataException();
        }

        private async Task<bool> Revoke(string runId) {
            try {
                await Call("POST", "/v1/runs/" + runId + "/stop", null, CancellationToken.None);
                return true;
            } catch (ApiException) { }
            catch (HttpRequestException) { }
            catch (OperationCanceledException) { }
            catch (IOException) { }
            return false;
        }

        private async Task<Dictionary<string, object>> Call(string method, string path, object data,
                CancellationToken cancellation, int seconds = 4) {
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation)) {
                deadline.CancelAfter(TimeSpan.FromSeconds(seconds));
                return await api.ComputerUseLab(method, path, data, deadline.Token);
            }
        }

        public void Dispose() { api.Dispose(); }
    }
}
