using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Authentication;

namespace Troika.Desktop {
    public sealed class ApiClient : IDisposable {
        public const string Production = "https://api.zhulebino-teahouse.ru";
        private readonly HttpClient http;
        private readonly Uri origin;
        private readonly SemaphoreSlim refreshGate = new SemaphoreSlim(1, 1);
        public AccountSession Account = new AccountSession();
        public string SessionId = "";
        public Action<AccountSession> SaveSession;
        public string ActiveRun = "";
        public PersonalProviderStore PersonalProviders;
        public ApiClient() : this(new HttpClientHandler { AllowAutoRedirect = false }, Production) { }
        public ApiClient(HttpMessageHandler handler, string endpoint) {
            origin = new Uri(endpoint.TrimEnd('/') + "/");
            if (origin.Scheme != "https" && !origin.IsLoopback) throw new ArgumentException("Требуется HTTPS.");
            http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(100) };
        }
        private Uri Address(string path) {
            var uri = new Uri(origin, path);
            if (uri.Scheme != origin.Scheme || uri.Authority != origin.Authority) throw new InvalidOperationException("Ссылка ведёт на другой сервер.");
            return uri;
        }
        private HttpRequestMessage Request(string method, string path, HttpContent content, bool auth) {
            var request = new HttpRequestMessage(new HttpMethod(method), Address(path));
            request.Content = content;
            if (auth) {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", Account.Token);
                request.Headers.Add("X-Hermes-Session-Key", SessionId);
                request.Headers.Add("X-Hermes-Session-Id", SessionId);
                if (method == "POST" && (path == "/v1/runs" || path == "/v1/chat/completions" || path == "/v1/responses")) {
                    if (PersonalProviders != null) PersonalProviders.Apply(request, Account.Email);
                }
            }
            return request;
        }
        private static StringContent Body(object value) { return value == null ? null : new StringContent(Json.Encode(value), Encoding.UTF8, "application/json"); }
        private async Task<HttpResponseMessage> Send(HttpRequestMessage request, HttpCompletionOption completion, CancellationToken cancellation) {
            var content = request.Content == null ? null : await request.Content.ReadAsByteArrayAsync();
            for (int attempt = 0; ; attempt++) {
                Exception failure = null;
                using (var copy = new HttpRequestMessage(request.Method, request.RequestUri)) {
                    foreach (var header in request.Headers) copy.Headers.TryAddWithoutValidation(header.Key, header.Value);
                    if (content != null) { copy.Content = new ByteArrayContent(content); foreach (var header in request.Content.Headers) copy.Content.Headers.TryAddWithoutValidation(header.Key, header.Value); }
                    try { return await http.SendAsync(copy, completion, cancellation); }
                    catch (HttpRequestException error) {
                        bool handshake = false;
                        for (Exception inner = error; inner != null; inner = inner.InnerException) {
                            var web = inner as WebException;
                            if (inner is AuthenticationException || web != null && web.Status == WebExceptionStatus.SecureChannelFailure) handshake = true;
                        }
                        if (!handshake || attempt >= 2) throw;
                        failure = error;
                    }
                }
                if (failure != null) await Task.Delay(attempt == 0 ? 300 : 1200, cancellation);
            }
        }
        private static string Error(string body, int status) {
            var resource = Json.Map(Json.Get(SafeParse(body), "error"));
            switch (Json.Text(resource, "code")) {
                case "monthly_resource_exhausted": return "Недостаточно AI-токенов. Остаток и время обновления указаны в аккаунте.";
                case "resource_usage_unknown": return "Расход уточняется; резерв сохранён. Повтор остановлен.";
                case "resource_budget_approval_required": return "Достигнут предел расходов задачи. Продолжение требует подтверждения.";
                case "subscription_concurrency_exceeded": return "Сначала завершите текущую задачу на аккаунте.";
                case "subscription_feature_not_available": return "Функция недоступна на тарифе или её лимит исчерпан.";
                case "resource_price_unavailable": case "unmetered_provider_route": return "Учёт расходов этой функции ещё не подключён.";
                case "resource_price_change_requires_approval": return "Коэффициенты изменились внутри оплаченного периода. Новое списание остановлено до согласования.";
            }
            if (status == 401 || status == 403) return "Войдите в аккаунт заново: доступ истёк или отозван.";
            if (status == 429) {
                var error = Json.Map(Json.Get(SafeParse(body), "error"));
                return Json.Text(error, "code") == "daily_request_limit_exceeded" ? "Дневной лимит исчерпан. В аккаунте указано время обновления." : "Сервис занят. Попробуйте немного позже.";
            }
            if (status == 404) return "Данные недоступны или срок передачи файла истёк.";
            if (status == 400) return "Проверьте введённые данные. Пароль при регистрации: от 10 до 128 символов.";
            if (status == 409) return "Аккаунт уже существует или действие уже завершено.";
            return "Сервер не выполнил запрос (" + status + "). Попробуйте снова.";
        }
        private static Dictionary<string, object> SafeParse(string body) { try { return Json.Parse(body); } catch { return new Dictionary<string, object>(); } }
        private async Task Check(HttpResponseMessage response) {
            if (!response.IsSuccessStatusCode) throw new ApiException(Error(await response.Content.ReadAsStringAsync(), (int)response.StatusCode), (int)response.StatusCode);
        }
        public async Task<Dictionary<string, object>> Call(string method, string path, object data, CancellationToken cancellation) {
            await EnsureSession(false, cancellation);
            if (method == "POST" && (path == "/v1/runs" || path == "/v1/chat/completions" || path == "/v1/responses") && PersonalProviders != null && PersonalProviders.Load(Account.Email).Count > 0) {
                using (var check = Request("GET", "/v1/subscription", null, true))
                using (var response = await Send(check, HttpCompletionOption.ResponseContentRead, cancellation)) {
                    await Check(response);
                    if (!Json.Flag(Json.Map(Json.Get(Json.Parse(await response.Content.ReadAsStringAsync()), "subscription")), "byok_enabled")) throw new InvalidOperationException("Сервер не поддерживает личный API. Ключ Тройки не использован.");
                }
            }
            for (int attempt = 0; ; attempt++) {
                using (var request = Request(method, path, Body(data), true))
                using (var response = await Send(request, HttpCompletionOption.ResponseContentRead, cancellation)) {
                    if (response.StatusCode == HttpStatusCode.Unauthorized && attempt == 0) { await EnsureSession(true, cancellation); continue; }
                    await Check(response);
                    return Json.Parse(await response.Content.ReadAsStringAsync());
                }
            }
        }
        public Task<Dictionary<string, object>> Get(string path, CancellationToken cancellation) { return Call("GET", path, null, cancellation); }
        public async Task Authenticate(string email, string password, bool register, CancellationToken cancellation) {
            using (var request = Request("POST", register ? "/v1/auth/register" : "/v1/auth/login", Body(new { email = email.Trim(), password = password, device_name = "Troika Desktop", platform = "windows" }), false))
            using (var response = await Send(request, HttpCompletionOption.ResponseContentRead, cancellation)) {
                await Check(response);
                var value = Json.Parse(await response.Content.ReadAsStringAsync());
                var next = ReadSession(value, email.Trim());
                if (!next.SignedIn) throw new InvalidDataException("Сервер не вернул защищённую сессию аккаунта.");
                Account = next; SessionId = next.HomeSession;
                if (SaveSession != null) SaveSession(next);
            }
        }
        private static AccountSession ReadSession(Dictionary<string, object> value, string email) {
            var token = Json.Text(value, "access_token");
            if (token.Length == 0) token = Json.Text(value, "token");
            var device = Json.Map(Json.Get(value, "device"));
            return new AccountSession { Email = email, Token = token, RefreshToken = Json.Text(value, "refresh_token"), ExpiresAt = Json.Number(value, "access_expires_at"), HomeSession = Json.Text(value, "home_session_id"), DeviceId = Json.Text(device, "id") };
        }
        public async Task EnsureSession(bool force, CancellationToken cancellation) {
            await refreshGate.WaitAsync(cancellation);
            try {
                if (!Account.SignedIn) throw new ApiException("Войдите в аккаунт, чтобы обратиться к Тройке.", 401);
                var now = (DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds;
                if (!force && Account.ExpiresAt > now + 300) return;
                using (var request = Request("POST", "/v1/auth/refresh", Body(new { refresh_token = Account.RefreshToken }), false))
                using (var response = await Send(request, HttpCompletionOption.ResponseContentRead, cancellation)) {
                    await Check(response);
                    var next = ReadSession(Json.Parse(await response.Content.ReadAsStringAsync()), Account.Email);
                    if (!next.SignedIn || next.ExpiresAt <= now) throw new ApiException("Войдите в аккаунт заново.", 401);
                    if (next.DeviceId.Length == 0) next.DeviceId = Account.DeviceId;
                    Account = next;
                    if (SessionId.Length == 0) SessionId = next.HomeSession;
                    if (SaveSession != null) SaveSession(next);
                }
            } finally { refreshGate.Release(); }
        }
        public async Task<string> Run(string input, Action<Dictionary<string, object>> activity, Func<Dictionary<string, object>, Task<string>> approval, CancellationToken cancellation) {
            var capabilities = await Get("/v1/capabilities", cancellation);
            if (!Json.Flag(Json.Map(Json.Get(capabilities, "features")), "device_file_delivery")) throw new InvalidOperationException("Обновите сервер: требуется локальное сохранение файлов.");
            var start = await Call("POST", "/v1/runs", new { input = input, session_id = SessionId, artifact_delivery = "device" }, cancellation);
            ActiveRun = Json.Text(start, "run_id");
            if (ActiveRun.Length == 0) ActiveRun = Json.Text(start, "id");
            if (ActiveRun.Length == 0) throw new InvalidDataException("Сервер не вернул номер задачи.");
            var runPath = "/v1/runs/" + Uri.EscapeDataString(ActiveRun);
            var answer = new StringBuilder();
            bool completed = false;
            try {
                using (var request = Request("GET", runPath + "/events", null, true))
                using (var response = await Send(request, HttpCompletionOption.ResponseHeadersRead, cancellation)) {
                    await Check(response);
                    using (var stream = await response.Content.ReadAsStreamAsync())
                    using (var registration = cancellation.Register(() => stream.Dispose()))
                    using (var reader = new StreamReader(stream, Encoding.UTF8)) {
                        while (true) {
                            cancellation.ThrowIfCancellationRequested();
                            var line = await reader.ReadLineAsync();
                            if (line == null) break;
                            if (!line.StartsWith("data:")) continue;
                            var payload = line.Substring(5).Trim();
                            if (payload.Length == 0 || payload == "[DONE]") continue;
                            var ev = Json.Parse(payload);
                            var kind = Json.Text(ev, "event");
                            if (kind == "message.delta") answer.Append(Json.Text(ev, "delta"));
                            // Reasoning remains private; only action status and source metadata reach the UI.
                            if (kind != "reasoning.available" && activity != null) activity(ev);
                            if (kind == "approval.request") {
                                var choice = approval == null ? "deny" : await approval(ev);
                                bool allowed = choice == "deny";
                                var choices = Json.Get(ev, "choices") as System.Collections.IEnumerable;
                                if (choices != null) foreach (var item in choices) if (Convert.ToString(item) == choice) allowed = true;
                                await Call("POST", runPath + "/approval", new { choice = allowed ? choice : "deny" }, cancellation);
                            }
                            if (kind == "run.failed") throw new InvalidOperationException("Тройка не смогла завершить задачу. Частичный ответ не считается готовым результатом.");
                            if (kind == "run.cancelled") throw new OperationCanceledException(cancellation);
                            if (kind == "run.completed") { completed = true; break; }
                        }
                    }
                }
                if (!completed || answer.Length == 0) {
                    var result = await Get(runPath, cancellation);
                    if (Json.Text(result, "status") != "completed") throw new IOException("Соединение прервалось. Задача ещё не подтверждена как завершённая; проверьте историю.");
                    completed = true;
                    if (answer.Length == 0) { var output = Json.Get(result, "output") ?? Json.Get(result, "result") ?? Json.Get(result, "content"); answer.Append(Json.Content(output)); }
                }
                if (answer.Length == 0) throw new InvalidDataException("Задача завершилась без ответа. Проверьте файлы и историю.");
                return answer.ToString();
            } finally { if (completed) ActiveRun = ""; }
        }
        public async Task Stop(CancellationToken cancellation) {
            var id = ActiveRun;
            if (id.Length > 0) { await Call("POST", "/v1/runs/" + Uri.EscapeDataString(id) + "/stop", new { }, cancellation); if (ActiveRun == id) ActiveRun = ""; }
        }
        public async Task<byte[]> Download(string path, int maximumBytes, CancellationToken cancellation) {
            await EnsureSession(false, cancellation);
            using (var request = Request("GET", path, null, true))
            using (var response = await Send(request, HttpCompletionOption.ResponseHeadersRead, cancellation)) {
                await Check(response);
                if (response.Content.Headers.ContentLength > maximumBytes) throw new InvalidDataException("Файл превышает допустимый размер.");
                using (var stream = await response.Content.ReadAsStreamAsync())
                using (var output = new MemoryStream()) {
                    var buffer = new byte[8192]; int count;
                    while ((count = await stream.ReadAsync(buffer, 0, buffer.Length, cancellation)) > 0) {
                        if (output.Length + count > maximumBytes) throw new InvalidDataException("Файл превышает допустимый размер.");
                        output.Write(buffer, 0, count);
                    }
                    return output.ToArray();
                }
            }
        }
        public async Task<string> Transcribe(byte[] audio, CancellationToken cancellation) {
            await EnsureSession(false, cancellation);
            using (var form = new MultipartFormDataContent()) {
                var part = new ByteArrayContent(audio); part.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
                form.Add(part, "file", "voice.wav"); form.Add(new StringContent("ru"), "language");
                using (var request = Request("POST", "/v1/audio/transcriptions", form, true))
                using (var response = await Send(request, HttpCompletionOption.ResponseContentRead, cancellation)) { await Check(response); return Json.Text(Json.Parse(await response.Content.ReadAsStringAsync()), "text"); }
            }
        }
        public async Task<byte[]> Speech(string text, CancellationToken cancellation) {
            await EnsureSession(false, cancellation);
            using (var request = Request("POST", "/v1/audio/speech", Body(new { input = text, voice = "ru-RU-SvetlanaNeural", response_format = "mp3" }), true))
            using (var response = await Send(request, HttpCompletionOption.ResponseContentRead, cancellation)) { await Check(response); var audio = await response.Content.ReadAsByteArrayAsync(); if (audio.Length > 10 * 1024 * 1024) throw new InvalidDataException("Ответ слишком большой для озвучки."); return audio; }
        }
        public void Dispose() { http.Dispose(); refreshGate.Dispose(); }
    }
}
