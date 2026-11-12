using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Media.Imaging;
using Troika.Desktop;

internal sealed class ComputerUseVisionLab : IDisposable {
    private const int MaxFrameBytes = 1024 * 1024;
    private readonly HttpClient client;
    private readonly Uri endpoint;
    private readonly string token;
    private readonly Uri runEndpoint;
    private readonly string grantId;
    private int sent;
    internal readonly string RunLabel;
    internal string Provider { get; private set; }

    internal ComputerUseVisionLab(string address, string token, string runId = null, string grantId = null) {
        var origin = ComputerUseAgent.LoopbackOrigin(address);
        if (runId != null || grantId != null) {
            if (runId == null || !Regex.IsMatch(runId, @"\Arun_[a-f0-9]{32}\z")
                    || grantId == null || !Regex.IsMatch(grantId, @"\A[a-f0-9]{32}\z"))
                throw new ArgumentException("Нужны идентификаторы пробного запуска и разрешения.");
            runEndpoint = new Uri(origin, "/v1/runs/" + runId + "/computer-windows-vision/");
            this.grantId = grantId;
            RunLabel = runId.Substring(4, 8);
        }
        endpoint = runEndpoint == null ? new Uri(origin, "/v1/computer-lab/vision") : new Uri(runEndpoint, "frame");
        if (token == null || !Regex.IsMatch(token, @"\A[A-Za-z0-9_-]{32,128}\z"))
            throw new ArgumentException("Нужен ключ доступа к тестовому серверу.");
        this.token = token;
        client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false }) {
            Timeout = TimeSpan.FromSeconds(10),
            MaxResponseContentBufferSize = 2048
        };
    }

    internal static byte[] Encode(BitmapSource frame) {
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(frame, null, null, null));
        using (var stream = new MemoryStream()) {
            encoder.Save(stream);
            if (stream.Length > MaxFrameBytes) throw new InvalidDataException();
            return stream.ToArray();
        }
    }

    internal async Task PrepareAsync() {
        if (runEndpoint == null) return;
        var review = await GrantAsync("review", new { version = 1, grant_id = grantId }, CancellationToken.None)
            .ConfigureAwait(false);
        var provider = Json.Text(review, "vision_provider");
        if (Json.Text(review, "status") != "pending" || (provider != "openrouter" && provider != "fixture"))
            throw new InvalidOperationException("Разрешение на отправку кадра недоступно.");
        Provider = provider;
    }

    internal async Task<string> SendAsync(byte[] frame, int remainingMs, CancellationToken cancellation) {
        cancellation.ThrowIfCancellationRequested();
        if (frame.Length == 0 || frame.Length > MaxFrameBytes || remainingMs <= 0
                || Interlocked.Exchange(ref sent, 1) != 0)
            throw new InvalidOperationException();
        var started = Stopwatch.StartNew();
        if (runEndpoint != null) {
            if (Provider == null) throw new InvalidOperationException();
            var consent = await GrantAsync("consent",
                new { version = 1, grant_id = grantId, allow = true, vision_provider = Provider }, cancellation);
            if (Json.Text(consent, "status") != "active" || Json.Text(consent, "vision_provider") != Provider)
                throw new InvalidDataException();
            remainingMs = Math.Min(remainingMs - (int)started.ElapsedMilliseconds,
                (int)(Json.Number(consent, "expires_in_seconds") * 1000));
            if (remainingMs <= 0) throw new InvalidOperationException();
        }
        using (var request = Post(endpoint)) {
            if (runEndpoint != null) {
                request.Headers.Add("X-Troika-Grant-Id", grantId);
                request.Headers.Add("X-Troika-Frame-Remaining-Ms", remainingMs.ToString(CultureInfo.InvariantCulture));
            }
            request.Content = new ByteArrayContent(frame);
            request.Content.Headers.ContentType = new MediaTypeHeaderValue("image/png");
            using (var response = await client.SendAsync(request, cancellation)) {
                response.EnsureSuccessStatusCode();
                var reply = Json.Parse(await response.Content.ReadAsStringAsync());
                cancellation.ThrowIfCancellationRequested();
                if (runEndpoint != null) {
                    if (!ValidGrantReply(reply) || !Json.Flag(reply, "accepted")) throw new InvalidDataException();
                    return "Кадр принят тестовым запуском.";
                }
                string summary = Json.Get(reply, "summary") as string;
                if (reply.Count != 1 || string.IsNullOrWhiteSpace(summary) || summary.Length > 240
                        || !ComputerUseAgent.ValidGoal(summary))
                    throw new InvalidDataException();
                return summary;
            }
        }
    }

    private HttpRequestMessage Post(Uri address) {
        var request = new HttpRequestMessage(HttpMethod.Post, address);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return request;
    }

    private static bool ValidGrantReply(System.Collections.Generic.Dictionary<string, object> reply) {
        return object.Equals(Json.Get(reply, "version"), 1) && Json.Text(reply, "mode") == "windows_vision_lab";
    }

    private async Task<System.Collections.Generic.Dictionary<string, object>> GrantAsync(string operation, object data,
            CancellationToken cancellation) {
        using (var request = Post(new Uri(runEndpoint, operation))) {
            request.Content = new StringContent(Json.Encode(data), Encoding.UTF8, "application/json");
            using (var response = await client.SendAsync(request, cancellation).ConfigureAwait(false)) {
                response.EnsureSuccessStatusCode();
                var reply = Json.Parse(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
                if (!ValidGrantReply(reply)) throw new InvalidDataException();
                return reply;
            }
        }
    }

    internal async Task StopAsync() {
        if (runEndpoint == null) return;
        using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2))) {
            try { await GrantAsync("stop", new { version = 1, grant_id = grantId }, deadline.Token).ConfigureAwait(false); }
            catch (HttpRequestException) { }
            catch (OperationCanceledException) { }
            catch (IOException) { }
            catch (ArgumentException) { }
            catch (InvalidOperationException) { }
        }
    }

    public void Dispose() { client.Dispose(); }
}
