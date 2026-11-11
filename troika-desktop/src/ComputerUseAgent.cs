using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    internal sealed class ComputerUseAgent : IDisposable {
        private const int MaxSteps = 8;
        private const int MaxReplyBytes = 4096;
        private readonly HttpClient http;
        private readonly Uri endpoint;
        private readonly string token;

        internal ComputerUseAgent(string address, string token, HttpMessageHandler handler = null) {
            var origin = LoopbackOrigin(address);
            if (token == null || !Regex.IsMatch(token, @"\A[A-Za-z0-9_-]{32,128}\z"))
                throw new ArgumentException("Нужен ключ доступа к тестовому серверу.");
            endpoint = new Uri(origin, "/v1/computer-lab/next");
            this.token = token;
            http = new HttpClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false }) {
                Timeout = Timeout.InfiniteTimeSpan,
            };
        }

        internal static Uri LoopbackOrigin(string address) {
            Uri origin;
            if (!Uri.TryCreate(address, UriKind.Absolute, out origin) || origin.Scheme != "http" || origin.Host != "127.0.0.1"
                || origin.Port < 1024 || origin.AbsolutePath != "/" || origin.UserInfo.Length != 0
                || origin.Query.Length != 0 || origin.Fragment.Length != 0)
                throw new ArgumentException("Нужен адрес тестового сервера на 127.0.0.1.");
            return origin;
        }

        internal static bool ValidGoal(string goal) {
            if (string.IsNullOrWhiteSpace(goal) || goal.Length > 512) return false;
            foreach (char character in goal) if (char.IsControl(character)) return false;
            return true;
        }

        internal async Task<ComputerUseState> RunAsync(ComputerUseSession session, ComputerUseExecutor executor,
                string goal, CancellationToken cancellation) {
            if (!ValidGoal(goal)) return session.Finish(false);
            ComputerUseObservation observation = null;
            string last = "start";
            try {
                for (int step = 0; step < MaxSteps; step++) {
                    cancellation.ThrowIfCancellationRequested();
                    if (session.State != ComputerUseState.Active) return session.State;
                    var command = await Choose(goal, observation, last, cancellation).ConfigureAwait(false);
                    cancellation.ThrowIfCancellationRequested();
                    if (session.State != ComputerUseState.Active) return session.State;
                    var action = Json.Get(command, "action") as string;
                    if (action == "finish" && command.Count == 1) return session.Complete();
                    if (action == "inspect" && command.Count == 1) {
                        observation = await executor.InspectAsync().ConfigureAwait(false);
                        if (observation == null) return session.Finish(false);
                        last = "inspected";
                        continue;
                    }

                    Guid observationId;
                    if (observation == null || !Guid.TryParseExact(Json.Get(command, "observation_id") as string, "N", out observationId)
                            || observationId != observation.Id) return session.Finish(false);
                    var text = Json.Get(command, "text") as string;
                    ComputerUseCommandResult result;
                    if (action == "write" && command.Count == 3 && observation.CanWrite && text != null)
                        result = await executor.WriteAsync(observationId, text).ConfigureAwait(false);
                    else if (action == "save" && command.Count == 2 && observation.CanSave)
                        result = await executor.SaveAsync(observationId).ConfigureAwait(false);
                    else return session.Finish(false);

                    if (result == ComputerUseCommandResult.Verified) return session.State;
                    if (result == ComputerUseCommandResult.Applied) { observation = null; last = "written"; }
                    else if (result == ComputerUseCommandResult.StaleObservation) { observation = null; last = "stale_observation"; }
                    else if (result == ComputerUseCommandResult.InvalidText) last = "invalid_text";
                    else return session.Finish(false);
                }
            } catch (OperationCanceledException) {
                if (cancellation.IsCancellationRequested) session.Stop();
            } catch (HttpRequestException) { }
            catch (IOException) { }
            catch (ArgumentException) { }
            catch (InvalidOperationException) { }
            return session.Finish(false);
        }

        private async Task<Dictionary<string, object>> Choose(string goal, ComputerUseObservation observation,
                string last, CancellationToken cancellation) {
            var view = observation == null ? null : new {
                id = observation.Id.ToString("N"), can_write = observation.CanWrite, can_save = observation.CanSave,
            };
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation))
            using (var request = new HttpRequestMessage(HttpMethod.Post, endpoint)) {
                deadline.CancelAfter(TimeSpan.FromSeconds(25));
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
                request.Content = new StringContent(Json.Encode(new { version = 1, goal, observation = view, last_result = last }),
                    Encoding.UTF8, "application/json");
                using (var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token).ConfigureAwait(false)) {
                    response.EnsureSuccessStatusCode();
                    if (response.Content.Headers.ContentLength > MaxReplyBytes) throw new InvalidDataException();
                    using (var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    using (var body = new MemoryStream()) {
                        var buffer = new byte[1024];
                        for (;;) {
                            int count = await stream.ReadAsync(buffer, 0, buffer.Length, deadline.Token).ConfigureAwait(false);
                            if (count == 0) break;
                            if (body.Length + count > MaxReplyBytes) throw new InvalidDataException();
                            body.Write(buffer, 0, count);
                        }
                        return Json.Parse(new UTF8Encoding(false, true).GetString(body.ToArray()));
                    }
                }
            }
        }

        public void Dispose() { http.Dispose(); }
    }
}
