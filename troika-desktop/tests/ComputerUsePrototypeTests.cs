using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Threading;
using Troika.Desktop;

static class ComputerUsePrototypeTests {
    private const string LabToken = "test_computer_lab_token_for_one_process";
    private const string ModelText = "Текст выбран ответом модели.";
    private const string ModelGoal = "Напиши пробную строку и сохрани её.";

    private static void Assert(bool expected, string reason) {
        if (!expected) throw new InvalidOperationException(reason);
    }

    private static void Click(Button button) { button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }

    private static void CheckConsentAndExpiry() {
        TimeSpan now = TimeSpan.Zero;
        var declined = new ComputerUseSession(() => now);
        declined.Stop();
        Assert(!declined.Allow(), "Stopping before consent did not close the request.");
        var session = new ComputerUseSession(() => now);
        Assert(session.Arm(ComputerUseStep.Write, "sample") == null, "A write was accepted before consent.");
        Assert(session.Allow() && !session.Allow(), "Consent must start a single session.");
        Assert(session.Arm(ComputerUseStep.Save, "sample") == null, "A save was accepted before a write.");
        var stale = session.Arm(ComputerUseStep.Write, "sample", () => now < TimeSpan.FromSeconds(15));
        now = TimeSpan.FromSeconds(15);
        Assert(session.Consume(ComputerUseStep.Write) == null && stale.ObservationExpired && !stale.Result.Task.Result,
            "An observation that expired while queued was allowed to mutate the editor.");
        var permit = session.Arm(ComputerUseStep.Write, "sample");
        Assert(permit != null && session.Consume(ComputerUseStep.Write) == permit, "A permitted write could not start.");
        Assert(session.Consume(ComputerUseStep.Write) == null, "A repeated write callback got permission.");
        now = TimeSpan.FromSeconds(ComputerUseSession.ConsentSeconds);
        Assert(session.State == ComputerUseState.Expired && permit.Result.Task.IsCompleted && !permit.Result.Task.Result,
            "Expiry must close the grant and release a waiting executor.");
        session.Report(permit, true);
        Assert(session.Arm(ComputerUseStep.Save, "sample") == null && session.Finish(true) == ComputerUseState.Expired,
            "A late receipt revived an expired grant.");
        Console.WriteLine("PASS consent, action order, replay rejection and exact expiry");
    }

    private static async Task<ComputerUsePrototypeWindow> Open(ComputerUseAgent agent = null, ComputerUseWindowsRun run = null) {
        var window = new ComputerUsePrototypeWindow(new ComputerUseSession(), agent, run) {
            ShowActivated = false, ShowInTaskbar = false,
            WindowStartupLocation = WindowStartupLocation.Manual, Left = -10000, Top = -10000,
        };
        window.Show();
        window.UpdateLayout();
        await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        return window;
    }

    private static void Cleanup(ComputerUsePrototypeWindow window) {
        window.Close();
        if (File.Exists(window.OutputFile)) File.Delete(window.OutputFile);
        var folder = Path.GetDirectoryName(window.OutputFile);
        if (Directory.Exists(folder)) Directory.Delete(folder, false);
    }

    private static async Task<T> Bounded<T>(Task<T> task, int milliseconds = 12000) {
        Assert(task != null && await Task.WhenAny(task, Task.Delay(milliseconds)) == task, "The prototype did not finish in time.");
        return await task;
    }

    private static async Task CheckNativeSave() {
        var window = await Open();
        try {
            Assert(window.AllowButton.IsVisible && window.StopButton.IsVisible, "Consent and Stop must be visible in the prototype window.");
            Assert(!File.Exists(window.OutputFile), "Opening the window created a file without consent.");
            Click(window.AllowButton);
            Assert(await Bounded(window.Execution) == ComputerUseState.Verified, "The native write, save and readback were not verified.");
            Assert(File.ReadAllText(window.OutputFile) == ComputerUseExecutor.Sample, "The saved sample does not match.");
            Console.WriteLine("PASS native UI Automation write, save and exact file readback");
        } finally { Cleanup(window); }
    }

    private static AutomationElement FindFixture(IntPtr handle, string id) {
        var root = AutomationElement.FromHandle(handle);
        var control = root.FindFirst(TreeScope.Descendants, new PropertyCondition(AutomationElement.AutomationIdProperty, id));
        Assert(control != null, "The native test control is unavailable.");
        return control;
    }

    private static async Task CheckLateSaveAfterStop() {
        var window = await Open();
        try {
            var handle = new WindowInteropHelper(window).Handle;
            string id = AutomationProperties.GetAutomationId(window);
            var driver = new ComputerUseNativeDriver(handle, id, true);
            await Task.Run(() => driver.Invoke("write"));
            Assert(await Task.Run(() => driver.ReadEditor()) == "", "A child process wrote without permission.");
            Assert(window.Session.Allow(), "Consent could not be set for the fixture.");
            var write = window.Session.Arm(ComputerUseStep.Write, ComputerUseExecutor.Sample);
            await Task.Run(() => driver.Invoke("write"));
            Assert(await Bounded(write.Result.Task), "The fixture did not receive the native write.");

            var save = window.Session.Arm(ComputerUseStep.Save, ComputerUseExecutor.Sample);
            Assert(save != null, "Save was not pending before Stop.");
            Click(window.StopButton);
            await Task.Run(() => driver.Invoke("save"));
            await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            Assert(window.Session.State == ComputerUseState.Stopped && !await Bounded(save.Result.Task), "Local Stop did not revoke the pending save.");
            Assert(!File.Exists(window.OutputFile), "A native callback saved a file after Stop.");
            var text = await Task.Run(() => driver.ReadEditor());
            Assert(text == ComputerUseExecutor.Sample, "Stop should preserve the completed write.");
            Console.WriteLine("PASS cross-process UI Automation obeys local consent and Stop");
        } finally { Cleanup(window); }
    }

    private static async Task CheckNoOverwrite() {
        var window = await Open();
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(window.OutputFile));
            File.WriteAllText(window.OutputFile, "Existing test fixture");
            Click(window.AllowButton);
            Assert(await Bounded(window.Execution) == ComputerUseState.Failed, "An existing file was reported as a successful save.");
            Assert(File.ReadAllText(window.OutputFile) == "Existing test fixture", "The test file was overwritten.");
            Console.WriteLine("PASS save refuses to overwrite an existing file");
        } finally { Cleanup(window); }
    }

    private static async Task CheckWindowIdentity() {
        var window = await Open();
        try {
            Assert(window.Session.Allow(), "Could not start the fixture grant.");
            var wrongWindow = new ComputerUseExecutor(window.Session, new WindowInteropHelper(window).Handle,
                "troika-scratchpad-" + Guid.NewGuid().ToString("N"), window.OutputFile, isolated: true);
            Assert(await Bounded(wrongWindow.RunAsync()) == ComputerUseState.Failed, "An unapproved window was accepted.");
            Assert(!File.Exists(window.OutputFile), "The wrong window produced a file.");
            Console.WriteLine("PASS cross-process worker rejects a wrong window identity");
        } finally { Cleanup(window); }
    }

    private static async Task CheckDistinctCommands() {
        var window = await Open();
        try {
            var now = TimeSpan.Zero;
            var executor = new ComputerUseExecutor(window.Session, new WindowInteropHelper(window).Handle,
                AutomationProperties.GetAutomationId(window), window.OutputFile, () => now);
            Assert(await Bounded(executor.InspectAsync()) == null, "Inspect ran before consent.");
            Assert(window.Session.Allow(), "The command session could not start.");
            var expired = await Bounded(executor.InspectAsync());
            Assert(expired != null && expired.CanWrite && !expired.CanSave, "The empty editor exposed the wrong actions.");
            now = TimeSpan.FromSeconds(ComputerUseExecutor.ObservationSeconds);
            const string text = "Текст задан отдельной командой.";
            Assert(await Bounded(executor.WriteAsync(expired.Id, text)) == ComputerUseCommandResult.StaleObservation,
                "An expired observation authorized a native write.");
            var current = await Bounded(executor.InspectAsync());
            Assert(await Bounded(executor.WriteAsync(current.Id, "unsafe\0text")) == ComputerUseCommandResult.InvalidText,
                "A control character was accepted as text.");
            Assert(await Bounded(executor.WriteAsync(current.Id, text)) == ComputerUseCommandResult.Applied,
                "The command text was not applied.");
            Assert(!File.Exists(window.OutputFile), "Write saved without an explicit save command.");
            Assert(await Bounded(executor.SaveAsync(current.Id)) == ComputerUseCommandResult.StaleObservation,
                "An observation from before the write was accepted by save.");
            var written = await Bounded(executor.InspectAsync());
            Assert(written != null && !written.CanWrite && written.CanSave, "The written editor exposed the wrong actions.");
            Assert(await Bounded(executor.SaveAsync(written.Id)) == ComputerUseCommandResult.Verified,
                "The separate save command was not verified.");
            Assert(File.ReadAllText(window.OutputFile) == text, "The file did not contain the command text.");
            Console.WriteLine("PASS independent inspect, arbitrary bounded text, stale rejection and verified save");
        } finally { Cleanup(window); }
    }

    private sealed class PlannerFixture : HttpMessageHandler {
        internal readonly TaskCompletionSource<bool> WriteRequested = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource<bool> ReleaseWrite = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly bool delayWrite;
        internal int Calls;

        internal PlannerFixture(bool delayWrite = false) { this.delayWrite = delayWrite; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) {
            Interlocked.Increment(ref Calls);
            Assert(request.RequestUri == new Uri("http://127.0.0.1:8765/v1/computer-lab/next"), "Wrong model pilot endpoint.");
            Assert(request.Headers.Authorization != null && request.Headers.Authorization.Parameter == LabToken, "Lab token missing.");
            var body = Json.Parse(await request.Content.ReadAsStringAsync().ConfigureAwait(false));
            Assert(body.Count == 4 && Json.Text(body, "goal") == ModelGoal, "Unexpected data sent to the test planner.");
            var view = Json.Map(Json.Get(body, "observation"));
            object reply;
            if (view.Count == 0) {
                reply = new { action = "inspect" };
            } else {
                Assert(view.Count == 3 && view.ContainsKey("id") && view.ContainsKey("can_write") && view.ContainsKey("can_save"),
                    "The planner received extra observation fields.");
                if (Json.Flag(view, "can_write")) {
                    WriteRequested.TrySetResult(true);
                    if (delayWrite) await ReleaseWrite.Task.ConfigureAwait(false);
                    reply = new { action = "write", observation_id = Json.Text(view, "id"), text = ModelText };
                } else {
                    Assert(Json.Flag(view, "can_save"), "The editor did not expose save after write.");
                    reply = new { action = "save", observation_id = Json.Text(view, "id") };
                }
            }
            return new HttpResponseMessage(HttpStatusCode.OK) {
                Content = new StringContent(Json.Encode(reply), Encoding.UTF8, "application/json"),
            };
        }
    }

    private static async Task CheckModelPlan(ComputerUseAgent agent, PlannerFixture fixture = null) {
        var window = await Open(agent);
        try {
            window.TaskInput.Text = ModelGoal;
            Assert(window.Execution == null && (fixture == null || fixture.Calls == 0), "The planner ran before local consent.");
            Click(window.AllowButton);
            Assert(await Bounded(window.Execution) == ComputerUseState.Verified, "The selected model commands did not finish.");
            Assert(File.ReadAllText(window.OutputFile) == ModelText, "The file does not contain the planner's chosen text.");
            Assert(fixture == null || fixture.Calls == 4, "The planner was not asked to select each of the four commands.");
            Console.WriteLine("PASS model-selected cross-process inspect, write and verified save");
        } finally { Cleanup(window); }
    }

    private static async Task CheckStopCancelsPlanner() {
        var fixture = new PlannerFixture(true);
        using (var agent = new ComputerUseAgent("http://127.0.0.1:8765", LabToken, fixture)) {
            var window = await Open(agent);
            try {
                window.TaskInput.Text = ModelGoal;
                Click(window.AllowButton);
                Assert(await Bounded(fixture.WriteRequested.Task), "The planner did not reach the pending write.");
                Click(window.StopButton);
                fixture.ReleaseWrite.TrySetResult(true);
                Assert(await Bounded(window.Execution) == ComputerUseState.Stopped, "Late model reply overrode local Stop.");
                Assert(!File.Exists(window.OutputFile) && fixture.Calls == 2, "A stopped model session dispatched another command.");
                var handle = new WindowInteropHelper(window).Handle;
                string editor = AutomationProperties.GetAutomationId(window) + "-editor";
                var text = await Task.Run(() => ((ValuePattern)FindFixture(handle, editor).GetCurrentPattern(ValuePattern.Pattern)).Current.Value);
                Assert(text.Length == 0, "A late model reply wrote to the editor after Stop.");
                Console.WriteLine("PASS local Stop rejects a late model reply before mutation");
            } finally { fixture.ReleaseWrite.TrySetResult(true); Cleanup(window); }
        }
    }

    private sealed class ConsentFixture : HttpMessageHandler {
        internal static readonly string DeviceToken = "trk_live_" + new string('A', 43);
        private static readonly string GrantId = new string('c', 32);
        private static readonly string RunId = "run_" + new string('d', 32);
        internal readonly TaskCompletionSource<bool> ConsentSent = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource<bool> ReleaseConsent = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int Requests;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) {
            Interlocked.Increment(ref Requests);
            Assert(request.Headers.Authorization.Parameter == DeviceToken, "The request used the wrong device token.");
            var path = request.RequestUri.AbsolutePath;
            object response;
            if (request.Method == HttpMethod.Get) {
                Assert(path == "/v1/computer-dry-run/requests", "Unexpected request listing route.");
                response = new { version = 1, requests = new[] {
                    new { run_id = RunId, grant_id = GrantId, mode = "dry_run", status = "pending", platform = "windows" },
                }};
            } else {
                var body = Json.Parse(await request.Content.ReadAsStringAsync().ConfigureAwait(false));
                Assert(Json.Text(body, "grant_id") == GrantId && Json.Number(body, "version") == 1, "Consent targeted the wrong grant.");
                var prefix = "/v1/runs/" + RunId + "/computer-dry-run/";
                bool isConsent = path == prefix + "consent";
                Assert(isConsent || path == prefix + "stop", "Unexpected consent operation.");
                if (isConsent) {
                    Assert(Json.Flag(body, "allow"), "The allow button did not grant consent.");
                    ConsentSent.TrySetResult(true);
                    await ReleaseConsent.Task.ConfigureAwait(false);
                }
                response = new { version = 1, mode = "dry_run", grant_id = GrantId, status = isConsent ? "active" : "stopped" };
            }
            return new HttpResponseMessage(HttpStatusCode.OK) {
                Content = new StringContent(Json.Encode(response), Encoding.UTF8, "application/json"),
            };
        }
    }

    private static async Task<ComputerUseConsentWindow> OpenConsent(ApiClient client) {
        var window = new ComputerUseConsentWindow(client) {
            ShowActivated = false, ShowInTaskbar = false,
            WindowStartupLocation = WindowStartupLocation.Manual, Left = -10000, Top = -10000,
        };
        window.Show();
        await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        await WaitForOperation(window.Operation);
        return window;
    }

    private static async Task WaitForOperation(Task task) {
        Assert(task != null && await Task.WhenAny(task, Task.Delay(6000)) == task, "Consent operation timed out.");
        await task;
    }

    private static async Task CheckRemoteConsent(bool close) {
        var server = new ConsentFixture();
        using (var client = ComputerUseConsentWindow.Connect("http://127.0.0.1:8765", ConsentFixture.DeviceToken, server)) {
            var window = await OpenConsent(client);
            try {
                Assert(window.AllowButton.IsEnabled && window.DenyButton.IsEnabled && !window.StopButton.IsEnabled
                    && server.Requests == 1, "Opening the window must only fetch pending requests.");
                Click(window.AllowButton);
                var pending = window.Operation;
                Assert(await Bounded(server.ConsentSent.Task), "Allow did not send consent to the paired server.");
                Assert(window.StopButton.IsEnabled && !window.AllowButton.IsEnabled, "Stop is required while approval is in flight.");
                if (close) {
                    var closed = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    window.Closed += (sender, args) => closed.TrySetResult(true);
                    window.Close();
                    Assert(await Bounded(closed.Task), "Closing did not wait for the revocation request.");
                } else {
                    Click(window.StopButton);
                    await WaitForOperation(window.Operation);
                }
                server.ReleaseConsent.TrySetResult(true);
                await WaitForOperation(pending);
                Assert(server.Requests == 3 && window.Requests.Items.Count == 0 && !window.StopButton.IsEnabled,
                    "A late consent response reactivated a stopped grant.");
                Assert(window.RefreshButton.IsEnabled != close, "The consent window did not return to the expected state.");
                Console.WriteLine("PASS Windows consent rejects a late reply after " + (close ? "close" : "Stop"));
            } finally { server.ReleaseConsent.TrySetResult(true); if (window.IsVisible) window.Close(); }
        }
    }

    private static async Task CheckConsentEndpoint(string address) {
        using (var client = ComputerUseConsentWindow.Connect(address, Environment.GetEnvironmentVariable("TROIKA_COMPUTER_TEST_DEVICE_TOKEN"))) {
            var window = await OpenConsent(client);
            try {
                Assert(window.AllowButton.IsEnabled, "The test server did not deliver its pending Windows grant.");
                Click(window.AllowButton);
                await WaitForOperation(window.Operation);
                Assert(window.StopButton.IsEnabled && window.Requests.Items.Count == 0, "The server did not confirm consent.");
                Click(window.StopButton);
                await WaitForOperation(window.Operation);
                Assert(!window.StopButton.IsEnabled && window.RefreshButton.IsEnabled, "The server did not confirm Stop.");
                Console.WriteLine("PASS Windows consent window completed authenticated allow and Stop over HTTP");
            } finally { window.Close(); }
        }
    }

    private sealed class WindowsRunFixture : HttpMessageHandler {
        internal static readonly string GrantId = new string('e', 32);
        internal static readonly string RunId = "run_" + new string('f', 32);
        internal readonly TaskCompletionSource<bool> Pulling = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource<bool> Release = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        private int takes;
        internal bool Stopped;
        internal int Reports;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) {
            Assert(request.Headers.Authorization.Parameter == ConsentFixture.DeviceToken, "Windows Run used the wrong token.");
            string operation = request.RequestUri.Segments[request.RequestUri.Segments.Length - 1];
            object reply;
            if (operation == "consent") {
                var args = Json.Parse(await request.Content.ReadAsStringAsync().ConfigureAwait(false));
                Assert(Json.Flag(args, "text_input"), "The editor did not negotiate model text.");
                reply = new { version = 1, mode = "windows_lab", grant_id = GrantId, status = "active",
                    expires_in_seconds = 30, text_input = true };
            } else if (operation == "take" && ++takes == 1) {
                reply = new { version = 1, mode = "windows_lab",
                    command = new { id = new string('a', 32), sequence = 1, action = "inspect", expires_in_ms = 9000 }};
            } else if (operation == "take") {
                Pulling.TrySetResult(true);
                await Release.Task.ConfigureAwait(false);
                reply = new { version = 1, mode = "windows_lab",
                    command = new { id = new string('b', 32), sequence = 2, action = "write", expires_in_ms = 9000,
                        inspect_action_id = new string('a', 32), text = "Тестовый текст запоздавшей команды." }};
            } else {
                Stopped |= operation == "stop";
                if (operation == "report") Reports++;
                reply = new { version = 1, mode = "windows_lab", accepted = true };
            }
            return new HttpResponseMessage(HttpStatusCode.OK) {
                Content = new StringContent(Json.Encode(reply), Encoding.UTF8, "application/json"),
            };
        }
    }

    private static async Task CheckWindowsRunStopsLateCommand(bool expired) {
        var fixture = new WindowsRunFixture();
        long ticks = 0;
        using (var run = new ComputerUseWindowsRun("http://127.0.0.1:8765", ConsentFixture.DeviceToken,
                WindowsRunFixture.RunId, WindowsRunFixture.GrantId, fixture,
                clock: () => TimeSpan.FromTicks(Interlocked.Read(ref ticks)))) {
            var window = await Open(run: run);
            try {
                Click(window.AllowButton);
                Assert(await Bounded(fixture.Pulling.Task), "The editor did not request the write after inspecting.");
                if (expired) Interlocked.Exchange(ref ticks, TimeSpan.FromSeconds(10).Ticks);
                else Click(window.StopButton);
                fixture.Release.TrySetResult(true);
                var expected = expired ? ComputerUseState.Failed : ComputerUseState.Stopped;
                Assert(await Bounded(window.Execution) == expected, "The editor did not close the stale grant.");
                var handle = new WindowInteropHelper(window).Handle;
                string editor = AutomationProperties.GetAutomationId(window) + "-editor";
                var text = await Task.Run(() => ((ValuePattern)FindFixture(handle, editor).GetCurrentPattern(ValuePattern.Pattern)).Current.Value);
                Assert(fixture.Stopped && fixture.Reports == 1 && text.Length == 0 && !File.Exists(window.OutputFile),
                    "A late server response reached the native editor after Stop.");
                Console.WriteLine("PASS Windows Run rejects a delayed write after " + (expired ? "command expiry" : "local Stop"));
            } finally { fixture.Release.TrySetResult(true); Cleanup(window); }
        }
    }

    private static async Task CheckWindowsRunEndpoint(string address, string runId, string grantId, string expected) {
        using (var run = new ComputerUseWindowsRun(address, Environment.GetEnvironmentVariable("TROIKA_COMPUTER_TEST_DEVICE_TOKEN"),
                runId, grantId)) {
            var window = await Open(run: run);
            try {
                Assert(window.Execution == null && !File.Exists(window.OutputFile), "The Windows editor acted before local consent.");
                Click(window.AllowButton);
                Assert(await Bounded(window.Execution, 25000) == ComputerUseState.Verified, "The remote Run did not verify the file.");
                var actual = File.ReadAllBytes(window.OutputFile);
                var bytes = Encoding.UTF8.GetBytes(expected);
                Assert(actual.SequenceEqual(bytes), "Windows saved the wrong bytes.");
                Console.WriteLine("PASS native Windows Run received commands and verified exact file contents");
            } finally { Cleanup(window); }
        }
    }

    [STAThread] public static int Main(string[] args) {
        if (args.Length != 0 && args[0] == ComputerUseNativeDriver.WorkerArgument)
            return ComputerUseNativeDriver.WorkerMain(args);
        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        app.Dispatcher.BeginInvoke(new Action(async () => {
            try {
                if (args.Length == 5 && args[0] == "--windows-run-endpoint") {
                    await CheckWindowsRunEndpoint(args[1], args[2], args[3], args[4]);
                    app.Shutdown(0);
                    return;
                }
                if (args.Length == 2 && args[0] == "--consent-endpoint") {
                    await CheckConsentEndpoint(args[1]);
                    app.Shutdown(0);
                    return;
                }
                if (args.Length == 2 && args[0] == "--lab-endpoint") {
                    using (var agent = new ComputerUseAgent(args[1], Environment.GetEnvironmentVariable("TROIKA_COMPUTER_LAB_TOKEN")))
                        await CheckModelPlan(agent);
                    app.Shutdown(0);
                    return;
                }
                CheckConsentAndExpiry();
                await CheckNativeSave();
                await CheckLateSaveAfterStop();
                await CheckNoOverwrite();
                await CheckWindowIdentity();
                await CheckDistinctCommands();
                var planner = new PlannerFixture();
                using (var agent = new ComputerUseAgent("http://127.0.0.1:8765", LabToken, planner))
                    await CheckModelPlan(agent, planner);
                await CheckStopCancelsPlanner();
                await CheckRemoteConsent(false);
                await CheckRemoteConsent(true);
                await CheckWindowsRunStopsLateCommand(false);
                await CheckWindowsRunStopsLateCommand(true);
                app.Shutdown(0);
            } catch (Exception error) {
                Console.Error.WriteLine(error.Message);
                app.Shutdown(1);
            }
        }));
        return app.Run();
    }
}
