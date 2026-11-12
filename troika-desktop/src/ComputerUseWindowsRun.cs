using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Troika.Desktop {
    internal sealed class ComputerUseWindowsRun : IDisposable {
        private readonly ApiClient client;
        private readonly string prefix;
        private readonly string grantId;
        private readonly Func<TimeSpan> clock;
        internal readonly string RunLabel;

        internal ComputerUseWindowsRun(string address, string token, string runId, string grantId,
                HttpMessageHandler handler = null, Func<TimeSpan> clock = null) {
            if (runId == null || !Regex.IsMatch(runId, @"\Arun_[a-f0-9]{32}\z") || !ValidId(grantId))
                throw new ArgumentException("Нужны идентификаторы пробного запуска и разрешения.");
            client = ComputerUseConsentWindow.Connect(address, token, handler);
            prefix = "/v1/runs/" + runId + "/computer-windows-lab/";
            RunLabel = runId.Substring(4, 8);
            this.grantId = grantId;
            this.clock = clock ?? (() => Clock.Elapsed);
        }

        private static readonly Stopwatch Clock = Stopwatch.StartNew();

        internal async Task<ComputerUseState> RunAsync(ComputerUseSession session, ComputerUseExecutor executor,
                CancellationToken cancellation) {
            if (session.State != ComputerUseState.Active) return session.State;
            var grant = new { version = 1, grant_id = grantId };
            ComputerUseObservation observation = null;
            string inspectId = null;
            int sequence = 0;
            bool confirmed = false;
            try {
                var requestedConsentAt = clock();
                var consent = await Send("consent", new { version = 1, grant_id = grantId, allow = true, text_input = true }, cancellation)
                    .ConfigureAwait(false);
                double seconds = Json.Number(consent, "expires_in_seconds");
                if (Json.Text(consent, "grant_id") != grantId || Json.Text(consent, "status") != "active"
                        || !Json.Flag(consent, "text_input") || !(seconds > 0 && seconds <= ComputerUseSession.ConsentSeconds))
                    throw new InvalidDataException();
                session.Shorten(TimeSpan.FromSeconds(seconds) - (clock() - requestedConsentAt));

                while (session.State == ComputerUseState.Active) {
                    cancellation.ThrowIfCancellationRequested();
                    var requestedAt = clock();
                    var next = await Send("take", grant, cancellation).ConfigureAwait(false);
                    if (!next.ContainsKey("command")) throw new InvalidDataException();
                    var payload = Json.Get(next, "command");
                    if (payload == null) {
                        await Task.Delay(180, cancellation).ConfigureAwait(false);
                        continue;
                    }
                    var command = Json.Map(payload);
                    var id = Json.Text(command, "id");
                    var action = Json.Text(command, "action");
                    var milliseconds = Json.Get(command, "expires_in_ms");
                    if (!ValidId(id) || sequence >= 8 || !object.Equals(Json.Get(command, "sequence"), ++sequence)
                            || !(milliseconds is int) || (int)milliseconds < 1 || (int)milliseconds > 10000)
                        throw new InvalidDataException();
                    var expires = requestedAt.Add(TimeSpan.FromMilliseconds((int)milliseconds));
                    Func<bool> fresh = () => !cancellation.IsCancellationRequested && clock() < expires;
                    if (!fresh() || session.State != ComputerUseState.Active) break;

                    object report;
                    if (action == "inspect" && command.Count == 4) {
                        observation = await executor.InspectAsync().ConfigureAwait(false);
                        inspectId = observation == null ? null : id;
                        report = observation == null
                            ? (object)new { version = 1, grant_id = grantId, command_id = id, status = "failed" }
                            : new { version = 1, grant_id = grantId, command_id = id, status = "observed",
                                    can_write = observation.CanWrite, can_save = observation.CanSave };
                    } else if (action == "write" || action == "save") {
                        bool writing = action == "write";
                        string text = Json.Get(command, "text") as string;
                        if (command.Count != (writing ? 6 : 5) || (writing && text == null)
                                || (!writing && command.ContainsKey("text")))
                            throw new InvalidDataException();
                        var result = ComputerUseCommandResult.StaleObservation;
                        if (observation != null && Json.Text(command, "inspect_action_id") == inspectId) {
                            result = writing
                                ? await executor.WriteAsync(observation.Id, text, fresh).ConfigureAwait(false)
                                : await executor.SaveAsync(observation.Id, fresh).ConfigureAwait(false);
                        }
                        observation = null;
                        inspectId = null;
                        string status = result == ComputerUseCommandResult.Applied ? "applied"
                            : result == ComputerUseCommandResult.Verified ? "verified"
                            : result == ComputerUseCommandResult.StaleObservation ? "stale_state" : "failed";
                        report = new { version = 1, grant_id = grantId, command_id = id, status = status };
                    } else {
                        throw new InvalidDataException();
                    }
                    if (!fresh()) break;
                    var receipt = await Send("report", report, cancellation).ConfigureAwait(false);
                    if (!Json.Flag(receipt, "accepted")) throw new InvalidDataException();
                    confirmed = session.State == ComputerUseState.Verified;
                }
            } catch (OperationCanceledException) {
                if (cancellation.IsCancellationRequested) session.Stop();
            } catch (ApiException error) {
                if (error.Status == 404 || error.Status == 409) session.Stop();
            } catch (HttpRequestException) { }
            catch (IOException) { }
            catch (ArgumentException) { }
            catch (InvalidOperationException) { }
            finally {
                if (!confirmed) session.Finish(false);
            }
            if (!confirmed) await Revoke().ConfigureAwait(false);
            return session.State;
        }

        private async Task Revoke() {
            try {
                await Send("stop", new { version = 1, grant_id = grantId }, CancellationToken.None).ConfigureAwait(false);
            } catch (ApiException) { }
            catch (HttpRequestException) { }
            catch (OperationCanceledException) { }
            catch (IOException) { }
            catch (ArgumentException) { }
            catch (InvalidOperationException) { }
        }

        private async Task<Dictionary<string, object>> Send(string operation, object body, CancellationToken cancellation) {
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation)) {
                deadline.CancelAfter(TimeSpan.FromSeconds(3));
                var reply = await client.ComputerUseLab("POST", prefix + operation, body, deadline.Token).ConfigureAwait(false);
                if (!object.Equals(Json.Get(reply, "version"), 1) || Json.Text(reply, "mode") != "windows_lab")
                    throw new InvalidDataException();
                return reply;
            }
        }

        private static bool ValidId(string value) {
            return value != null && Regex.IsMatch(value, @"\A[a-f0-9]{32}\z");
        }

        public void Dispose() { client.Dispose(); }
    }
}
