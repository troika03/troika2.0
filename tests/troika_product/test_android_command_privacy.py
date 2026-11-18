"""Execute the real Android command boundary against an offline JVM fixture.

Platform calls are faked; the three production Kotlin classes are compiled
unchanged from the checkout. The fixture records intended Android effects and
WebSocket replies so privacy checks also cover callers, not just a formatter.
No emulator, account, device, Gradle download or network connection is used.
"""

from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "com.troika.hermes_assistant"
ANDROID_SOURCES = ROOT / "hermes-android/android/app/src"
PACKAGE_PATH = Path(*PACKAGE.split("."))
SOURCE = ANDROID_SOURCES / "main/kotlin" / PACKAGE_PATH


def _cached_jar(group, artifact, version):
    cache = Path(os.environ.get("GRADLE_USER_HOME", Path.home() / ".gradle"))
    matches = sorted((cache / "caches/modules-2/files-2.1" / group / artifact / version).glob("*/*.jar"))
    if not matches:
        pytest.skip(f"offline JVM fixture requires cached {artifact} {version}")
    return matches[0]


def _jdk():
    homes = [Path(os.environ.get("JAVA_HOME", ""))]
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    homes += sorted((program_files / "Microsoft").glob("jdk-21*"), reverse=True)
    java = shutil.which("javac")
    if java:
        homes.append(Path(java).resolve().parent.parent)
    suffix = ".exe" if os.name == "nt" else ""
    for home in homes:
        if (home / "bin" / ("javac" + suffix)).is_file():
            return home / "bin" / ("java" + suffix), home / "bin" / ("javac" + suffix)
    pytest.skip("offline Android command fixture requires an installed JDK")


def _android_jar():
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    roots.append(str(Path.home() / "AppData/Local/Android/sdk"))
    for root in roots:
        if root:
            for version in ("android-36", "android-36.1", "android-35"):
                jar = Path(root) / "platforms" / version / "android.jar"
                if jar.is_file():
                    return jar
    pytest.skip("offline Android command fixture requires a local Android 35+ SDK")


JAVA_FIXTURES = {
    "android/util/Log.java": """
package android.util;
public final class Log {
    public static final java.util.List<String> events = new java.util.concurrent.CopyOnWriteArrayList<>();
    public static int i(String tag, String value) { events.add(value); return 0; }
    public static int d(String tag, String value) { events.add(value); return 0; }
    public static int w(String tag, String value) { events.add(value); return 0; }
    public static int e(String tag, String value) { events.add(value); return 0; }
    public static int e(String tag, String value, Throwable error) { events.add(value + error); return 0; }
}
""",
    "android/os/Build.java": """
package android.os;
public final class Build {
    public static final String MODEL = "test-device";
    public static final class VERSION { public static int SDK_INT = 36; }
}
""",
    "android/os/Bundle.java": """
package android.os;
public class Bundle {
    private final java.util.Map<String,CharSequence> values = new java.util.HashMap<>();
    public void putCharSequence(String key, CharSequence value) { values.put(key, value); }
    public CharSequence getCharSequence(String key) { return values.get(key); }
}
""",
    "android/content/Context.java": """
package android.content;
public class Context {
    public Intent lastIntent;
    public boolean rejectIntent;
    public void startActivity(Intent intent) {
        if (rejectIntent) throw new IllegalStateException("private-fixture-secret");
        lastIntent = intent;
    }
    public Object getSystemService(String name) { return null; }
    public <T> T getSystemService(Class<T> type) { return null; }
    public SharedPreferences getSharedPreferences(String name, int mode) { return null; }
    public ContentResolver getContentResolver() { return null; }
    public String getPackageName() { return "fixture"; }
    public android.content.pm.PackageManager getPackageManager() { return new android.content.pm.PackageManager(); }
    public Context getApplicationContext() { return this; }
}
""",
    "android/content/pm/PackageManager.java": """
package android.content.pm;
public class PackageManager {
    public android.content.Intent getLaunchIntentForPackage(String name) { return null; }
    public java.util.List<ResolveInfo> queryIntentActivities(android.content.Intent intent, int flags) {
        return java.util.Collections.emptyList();
    }
}
""",
    "android/net/Uri.java": """
package android.net;
public class Uri {
    private final String value;
    private Uri(String value) { this.value = value; }
    public static Uri parse(String value) { return new Uri(value); }
    public static String encode(String value) {
        try { return java.net.URLEncoder.encode(value, "UTF-8"); }
        catch (java.io.UnsupportedEncodingException error) { throw new AssertionError(error); }
    }
    @Override public String toString() { return value; }
}
""",
    "android/content/Intent.java": """
package android.content;
public class Intent {
    public final String action;
    public android.net.Uri uri;
    public final java.util.Map<String,Object> extras = new java.util.HashMap<>();
    public Intent(String action) { this(action, null); }
    public Intent(String action, android.net.Uri uri) { this.action = action; this.uri = uri; }
    public Intent(Context context, Class<?> type) { this.action = type.getName(); }
    public Intent addFlags(int flags) { return this; }
    public Intent addCategory(String category) { return this; }
    public Intent setData(android.net.Uri value) { uri = value; return this; }
    public Intent putExtra(String key, String value) { extras.put(key, value); return this; }
    public Intent putExtra(String key, int value) { extras.put(key, value); return this; }
    public Intent putExtra(String key, boolean value) { extras.put(key, value); return this; }
}
""",
    "android/graphics/Rect.java": """
package android.graphics;
public class Rect {
    public int centerX() { return 10; }
    public int centerY() { return 10; }
    public int width() { return 20; }
    public int height() { return 20; }
}
""",
    "android/view/accessibility/AccessibilityNodeInfo.java": """
package android.view.accessibility;
public class AccessibilityNodeInfo {
    public CharSequence text = "";
    public CharSequence entered;
    public boolean failSet;
    public CharSequence getText() { return text; }
    public CharSequence getContentDescription() { return ""; }
    public CharSequence getHintText() { return ""; }
    public CharSequence getPackageName() { return "fixture.app"; }
    public String getViewIdResourceName() { return "fixture.input"; }
    public boolean isFocused() { return true; }
    public boolean isEditable() { return true; }
    public boolean isAccessibilityFocused() { return false; }
    public boolean isClickable() { return true; }
    public boolean isPassword() { return false; }
    public AccessibilityNodeInfo getParent() { return null; }
    public int getChildCount() { return 0; }
    public AccessibilityNodeInfo getChild(int index) { return null; }
    public void getBoundsInScreen(android.graphics.Rect rect) {}
    public boolean performAction(int action) { return true; }
    public boolean performAction(int action, android.os.Bundle args) {
        if (failSet) throw new IllegalStateException("private-fixture-secret");
        entered = args.getCharSequence("ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE");
        return true;
    }
}
""",
    "android/accessibilityservice/AccessibilityService.java": """
package android.accessibilityservice;
public class AccessibilityService extends android.content.Context {
    public android.view.accessibility.AccessibilityNodeInfo root;
    public android.view.accessibility.AccessibilityNodeInfo getRootInActiveWindow() { return root; }
    public android.view.accessibility.AccessibilityNodeInfo findFocus(int focus) { return root; }
    protected void onServiceConnected() {}
    public void onDestroy() {}
    public boolean performGlobalAction(int action) { return true; }
    public java.util.concurrent.Executor getMainExecutor() { return Runnable::run; }
    public void takeScreenshot(int display, java.util.concurrent.Executor executor, TakeScreenshotCallback callback) {
        throw new IllegalStateException("private-fixture-secret");
    }
    public interface TakeScreenshotCallback {
        void onSuccess(ScreenshotResult result);
        void onFailure(int error);
    }
    public static class ScreenshotResult {
        public android.hardware.HardwareBuffer getHardwareBuffer() { return null; }
        public android.graphics.ColorSpace getColorSpace() { return null; }
    }
}
""",
    "androidx/core/app/NotificationCompat.java": """
package androidx.core.app;
public class NotificationCompat {
    public static final int PRIORITY_HIGH = 1;
    public static class BigTextStyle { public BigTextStyle bigText(CharSequence value) { return this; } }
    public static class Builder {
        public Builder(android.content.Context context, String channel) {}
        public Builder setSmallIcon(int value) { return this; }
        public Builder setContentTitle(CharSequence value) { return this; }
        public Builder setContentText(CharSequence value) { return this; }
        public Builder setStyle(BigTextStyle value) { return this; }
        public Builder setPriority(int value) { return this; }
        public Builder setAutoCancel(boolean value) { return this; }
        public Builder setContentIntent(android.app.PendingIntent value) { return this; }
        public android.app.Notification build() { throw new IllegalStateException("private-fixture-secret"); }
    }
}
""",
    "okhttp3/Request.java": """
package okhttp3;
public class Request {
    public String url;
    public String authorization;
    public static class Builder {
        private final Request request = new Request();
        public Builder url(String url) { request.url = url; return this; }
        public Builder header(String name, String value) { request.authorization = value; return this; }
        public Request build() { return request; }
    }
}
""",
    "okhttp3/Response.java": "package okhttp3; public class Response {}",
    "okhttp3/WebSocket.java": """
package okhttp3;
public interface WebSocket { boolean send(String value); boolean close(int code, String reason); }
""",
    "okhttp3/WebSocketListener.java": """
package okhttp3;
public class WebSocketListener {
    public void onOpen(WebSocket socket, Response response) {}
    public void onMessage(WebSocket socket, String text) {}
    public void onClosing(WebSocket socket, int code, String reason) {}
    public void onClosed(WebSocket socket, int code, String reason) {}
    public void onFailure(WebSocket socket, Throwable error, Response response) {}
}
""",
    "okhttp3/OkHttpClient.java": """
package okhttp3;
public class OkHttpClient {
    public static Request request;
    public static WebSocketListener listener;
    public static final java.util.List<String> replies = new java.util.concurrent.CopyOnWriteArrayList<>();
    public static WebSocket socket = new WebSocket() {
        public boolean send(String value) { replies.add(value); return true; }
        public boolean close(int code, String reason) { return true; }
    };
    public WebSocket newWebSocket(Request value, WebSocketListener handler) {
        request = value; listener = handler; return socket;
    }
    public static class Builder {
        public Builder pingInterval(long value, java.util.concurrent.TimeUnit unit) { return this; }
        public Builder readTimeout(long value, java.util.concurrent.TimeUnit unit) { return this; }
        public Builder writeTimeout(long value, java.util.concurrent.TimeUnit unit) { return this; }
        public Builder connectTimeout(long value, java.util.concurrent.TimeUnit unit) { return this; }
        public OkHttpClient build() { return new OkHttpClient(); }
    }
}
""",
}


KOTLIN_FIXTURES = """
package com.troika.hermes_assistant
import android.content.Context
import org.json.JSONObject
class MainActivity
object HermesListenerService { const val PREFS="fixture"; const val PREF_URL="url"; const val PREF_KEY="key" }
class EdgeTtsPlayer(vararg args: Any?) { fun speak(text: String, done: () -> Unit) { done() }; fun stop() {} }
object ScreenCaptureService { fun capture(vararg args: Any?) = JSONObject().put("ok", true) }
object PhoneFiles {
    fun listFiles(vararg args: Any?) = JSONObject().put("ok", true)
    fun readFile(vararg args: Any?) = JSONObject().put("ok", true).put("content", "private-fixture-secret")
    fun writeFile(vararg args: Any?) = JSONObject().put("ok", true)
    fun deleteFile(vararg args: Any?) = JSONObject().put("ok", true)
    fun moveFile(vararg args: Any?) = JSONObject().put("ok", true)
    fun fileInfo(vararg args: Any?) = JSONObject().put("ok", true)
    fun saveToGallery(vararg args: Any?) = JSONObject().put("ok", true)
    fun hasAllFilesAccess() = false
}
object PhoneSystem {
    fun clipboardGet(vararg args: Any?) = JSONObject().put("ok", true)
    fun clipboardSet(vararg args: Any?): JSONObject = throw IllegalStateException("private-fixture-secret")
    fun torch(vararg args: Any?) = JSONObject().put("ok", true)
    fun torchToggle(vararg args: Any?) = JSONObject().put("ok", true)
    fun battery(vararg args: Any?) = JSONObject().put("ok", true)
    fun network(vararg args: Any?) = JSONObject().put("ok", true)
    fun cameraTakePhoto(vararg args: Any?) = JSONObject().put("ok", true)
}
object PhoneCalendar {
    fun listCalendars(vararg args: Any?) = JSONObject().put("ok", true)
    fun listEvents(vararg args: Any?) = JSONObject().put("ok", true)
    fun createEvent(vararg args: Any?) = JSONObject().put("ok", true)
    fun updateEvent(vararg args: Any?) = JSONObject().put("ok", true)
    fun deleteEvent(vararg args: Any?) = JSONObject().put("ok", true)
    fun requestPermissions(vararg args: Any?) = JSONObject().put("ok", true)
}
"""


HARNESS = """
package com.troika.hermes_assistant;
import android.content.Context;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;
import com.troika.hermes_assistant.*;
import okhttp3.*;
import org.json.JSONObject;

public class AndroidCommandPrivacyHarness {
    private static final String PRIVATE = "private-fixture-secret";
    private static int checks;
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
        checks++;
    }
    private static void safe(Object value, String message) {
        check(!String.valueOf(value).contains(PRIVATE), message);
    }
    private static JSONObject params(String key) { return new JSONObject().put(key, PRIVATE); }
    private static JSONObject execute(Context context, String action, JSONObject params) {
        return PhoneCommandExecutor.INSTANCE.execute(context, action, params);
    }
    private static JSONObject reply(String action, JSONObject params) throws Exception {
        int before = OkHttpClient.replies.size();
        OkHttpClient.listener.onMessage(OkHttpClient.socket,
            new JSONObject().put("id", "fixture-id").put("action", action).put("params", params).toString());
        long deadline = System.nanoTime() + 3_000_000_000L;
        while (OkHttpClient.replies.size() == before && System.nanoTime() < deadline) Thread.sleep(5);
        check(OkHttpClient.replies.size() > before, "command must produce a reply");
        JSONObject envelope = new JSONObject(OkHttpClient.replies.get(before));
        check(envelope.getString("id").equals("fixture-id"), "correlation id preserved");
        return envelope.getJSONObject("result");
    }
    public static void main(String[] args) throws Exception {
        Context context = new Context();
        PhoneBridgeClient bridge = new PhoneBridgeClient(context, "https://" + PRIVATE + ".invalid", PRIVATE);
        bridge.start();
        check(OkHttpClient.request.authorization.equals("Bearer " + PRIVATE), "authentication forwarded");
        check(OkHttpClient.request.url.contains(PRIVATE), "target URL forwarded");
        safe(Log.events, "connection log must not contain URL or token");

        JSONObject unknown = reply(PRIVATE, params("text"));
        check(!unknown.getBoolean("ok"), "unknown command rejected");
        check(unknown.getString("error").equals("unknown_action"), "unknown command has bounded code");
        safe(unknown, "unknown command error must not echo input");
        OkHttpClient.listener.onMessage(OkHttpClient.socket, PRIVATE + "{malformed");
        safe(Log.events, "malformed and unknown payloads must not enter logs");

        JSONObject failure = reply("clipboard_set", params("text"));
        check(failure.getString("error").equals("executor_failed"), "executor exception has stable code");
        safe(failure, "executor response must not echo exception content");
        safe(Log.events, "executor logs must omit exception and stack details");

        HermesAccessibilityService service = new HermesAccessibilityService();
        AccessibilityNodeInfo node = new AccessibilityNodeInfo();
        node.text = PRIVATE;
        service.root = node;
        service.onServiceConnected();
        JSONObject typed = reply("type_text", params("text"));
        check(typed.getBoolean("ok"), "text command succeeds");
        check(PRIVATE.contentEquals(node.entered), "text still reaches intended input");
        safe(typed, "successful text command must not echo text");
        JSONObject tapped = execute(context, "tap", params("text"));
        check(tapped.getBoolean("ok"), "label-based click still succeeds");
        safe(tapped, "click receipt must not echo node label");

        node.failSet = true;
        JSONObject inputFailure = execute(context, "type_text", params("text"));
        check(inputFailure.getString("error").equals("a11y_error"), "input exception bounded");
        safe(inputFailure, "input exception must not echo private details");
        safe(service.takeScreenshot(), "screenshot exception must not echo private details");
        node.failSet = false;

        JSONObject read = execute(context, "read_screen", new JSONObject());
        check(read.toString().contains(PRIVATE), "requested screen read retains its actual content");
        JSONObject file = execute(context, "file_read", params("path"));
        check(file.getString("content").equals(PRIVATE), "requested file read is unchanged");
        safe(Log.events, "intentional reads must not be copied to diagnostics");

        for (String action : new String[]{"call", "navigate", "web_search", "open_url", "send_sms"}) {
            JSONObject input = new JSONObject().put("number", PRIVATE).put("destination", PRIVATE)
                .put("query", PRIVATE).put("url", "https://example.invalid/" + PRIVATE).put("text", PRIVATE);
            JSONObject result = execute(context, action, input);
            check(result.getBoolean("ok"), "Intent action must succeed");
            safe(result, "Intent receipt must not echo private argument");
            check(context.lastIntent.uri.toString().contains(PRIVATE), "actual Intent target preserved");
            if (action.equals("send_sms"))
                check(context.lastIntent.extras.get("sms_body").equals(PRIVATE), "SMS draft text preserved");
        }
        context.rejectIntent = true;
        JSONObject urlFailure = execute(context, "open_url", params("url"));
        check(urlFailure.getString("error").equals("invalid_url"), "URL exception bounded");
        safe(urlFailure, "URL exception must not disclose content");
        JSONObject missingApp = execute(context, "open_app", params("app"));
        safe(missingApp, "unavailable app must not echo query");

        bridge.stop();
        OkHttpClient.listener.onClosing(OkHttpClient.socket, 1000, PRIVATE);
        OkHttpClient.listener.onClosed(OkHttpClient.socket, 1000, PRIVATE);
        OkHttpClient.listener.onFailure(OkHttpClient.socket, new IllegalStateException(PRIVATE), null);
        safe(Log.events, "close reason and transport exception must not enter logs");
        System.out.println("ANDROID_COMMAND_PRIVACY checks=" + checks);
    }
}
"""


def _run(command, cwd, timeout=90):
    result = subprocess.run([str(part) for part in command], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    return result.stdout


def _kotlin_compiler():
    return [
        _cached_jar("org.jetbrains.kotlin", "kotlin-compiler-embeddable", "2.2.20"),
        _cached_jar("org.jetbrains.kotlin", "kotlin-stdlib", "2.2.20"),
        _cached_jar("org.jetbrains.kotlin", "kotlin-script-runtime", "2.2.20"),
        _cached_jar("org.jetbrains.kotlin", "kotlin-reflect", "2.2.0"),
        _cached_jar("org.jetbrains.kotlinx", "kotlinx-coroutines-core-jvm", "1.9.0"),
        _cached_jar("org.jetbrains", "annotations", "13.0"),
    ]


def _compile_kotlin(java, compiler, classpath, sources, destination, cwd):
    _run([java, "-cp", os.pathsep.join(map(str, compiler)), "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
          "-no-stdlib", "-no-reflect", "-classpath", os.pathsep.join(map(str, classpath)),
          "-d", destination, *sources], cwd)


def test_android_command_callers_do_not_log_or_echo_private_payloads(tmp_path):
    java, javac = _jdk()
    android = _android_jar()
    compiler = _kotlin_compiler()
    json_jar = _cached_jar("org.json", "json", "20180813")
    stubs, production, tests = [tmp_path / name for name in ("stubs", "production", "tests")]
    for directory in (stubs, production, tests):
        directory.mkdir()
    java_sources = []
    for relative, text in JAVA_FIXTURES.items():
        path = tmp_path / "java" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        java_sources.append(path)
    _run([javac, "-encoding", "UTF-8", "-classpath", android, "-d", stubs, *java_sources], tmp_path)
    app_fixtures = tmp_path / "AppFixtures.kt"
    app_fixtures.write_text(KOTLIN_FIXTURES, encoding="utf-8")
    classpath = [android, stubs, json_jar, compiler[1], compiler[-1]]
    sources = [SOURCE / name for name in ("PhoneBridgeClient.kt", "AppNameResolver.kt", "PhoneCommandExecutor.kt", "HermesAccessibilityService.kt")]
    _compile_kotlin(java, compiler, classpath, [*sources, app_fixtures], production, tmp_path)
    harness = tmp_path / "AndroidCommandPrivacyHarness.java"
    harness.write_text(HARNESS, encoding="utf-8")
    runtime = os.pathsep.join(map(str, [tests, production, stubs, json_jar, compiler[1], android]))
    _run([javac, "-encoding", "UTF-8", "-classpath", runtime, "-d", tests, harness], tmp_path)
    output = _run([java, "-cp", runtime, "com.troika.hermes_assistant.AndroidCommandPrivacyHarness"], tmp_path, timeout=15)
    assert "ANDROID_COMMAND_PRIVACY checks=" in output


def test_debug_computer_use_compiles_against_sdk_and_checks_session(tmp_path):
    java, _ = _jdk()
    android = _android_jar()
    compiler = _kotlin_compiler()
    junit = _cached_jar("junit", "junit", "4.12")
    hamcrest = _cached_jar("org.hamcrest", "hamcrest-core", "1.3")
    generated_ids = tmp_path / "R.kt"
    generated_ids.write_text(
        f"package {PACKAGE}\nobject R {{ object id {{ const val troika_computer_lab_editor = 1 }} }}\n",
        encoding="utf-8",
    )
    debug = ANDROID_SOURCES / "debug/kotlin" / PACKAGE_PATH
    tests = ANDROID_SOURCES / "testDebug/kotlin" / PACKAGE_PATH
    sources = [
        SOURCE / "HermesAccessibilityService.kt",
        debug / "AndroidComputerUseSession.kt",
        debug / "ComputerUseLabActivity.kt",
        tests / "AndroidComputerUseSessionTest.kt",
        generated_ids,
    ]
    classes = tmp_path / "classes"
    _compile_kotlin(java, compiler, [android, compiler[1], compiler[-1], junit], sources, classes, tmp_path)
    runtime = os.pathsep.join(map(str, [classes, compiler[1], junit, hamcrest]))
    _run([java, "-cp", runtime, "org.junit.runner.JUnitCore", f"{PACKAGE}.AndroidComputerUseSessionTest"],
         tmp_path, timeout=15)
