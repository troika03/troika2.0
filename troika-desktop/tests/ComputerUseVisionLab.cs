using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
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
    private int sent;

    internal ComputerUseVisionLab(string address, string token) {
        endpoint = new Uri(ComputerUseAgent.LoopbackOrigin(address), "/v1/computer-lab/vision");
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

    internal async Task<string> SendAsync(byte[] frame, CancellationToken cancellation) {
        cancellation.ThrowIfCancellationRequested();
        if (frame.Length == 0 || frame.Length > MaxFrameBytes || Interlocked.Exchange(ref sent, 1) != 0)
            throw new InvalidOperationException();
        using (var request = new HttpRequestMessage(HttpMethod.Post, endpoint)) {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            request.Content = new ByteArrayContent(frame);
            request.Content.Headers.ContentType = new MediaTypeHeaderValue("image/png");
            using (var response = await client.SendAsync(request, cancellation)) {
                response.EnsureSuccessStatusCode();
                var reply = Json.Parse(await response.Content.ReadAsStringAsync());
                cancellation.ThrowIfCancellationRequested();
                string summary = Json.Get(reply, "summary") as string;
                if (reply.Count != 1 || string.IsNullOrWhiteSpace(summary) || summary.Length > 240
                        || !ComputerUseAgent.ValidGoal(summary))
                    throw new InvalidDataException();
                return summary;
            }
        }
    }

    public void Dispose() { client.Dispose(); }
}
