package com.troika.hermes_assistant

import android.annotation.SuppressLint
import android.app.Activity
import android.app.Application
import android.os.Bundle
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.webkit.*
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.io.ByteArrayInputStream

/** Offline worker runtime. No JS/Java bridge, file/content URLs, or network. */
class DevelopmentCheckBridge(private val activity: Activity, engine: FlutterEngine) {
    private val handler = Handler(Looper.getMainLooper())
    private var view: WebView? = null
    private var pending: MethodChannel.Result? = null
    private var timeout: Runnable? = null
    private var poll: Runnable? = null
    private val channel = MethodChannel(engine.dartExecutor.binaryMessenger, "troika/development")

    init {
        activity.application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityDestroyed(target: Activity) {
                if (target !== activity) return
                finish(JSONObject().put("exit_code", -1).put("output", "Проверка остановлена.").put("cancelled", true))
                channel.setMethodCallHandler(null)
                activity.application.unregisterActivityLifecycleCallbacks(this)
            }
            override fun onActivityCreated(target: Activity, saved: Bundle?) {}
            override fun onActivityStarted(target: Activity) {}
            override fun onActivityResumed(target: Activity) {}
            override fun onActivityPaused(target: Activity) {}
            override fun onActivityStopped(target: Activity) {}
            override fun onActivitySaveInstanceState(target: Activity, saved: Bundle) {}
        })
        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "stop" -> { finish(JSONObject().put("exit_code", -1).put("output", "Проверка остановлена.").put("cancelled", true)); result.success(null) }
                "check" -> {
                    if (pending != null) { result.error("check_busy", "Проверка уже выполняется.", null); return@setMethodCallHandler }
                    val files = call.argument<Map<String, String>>("files")
                    val mode = call.argument<String>("mode")
                    if (files == null || files.size !in 1..100 || files.values.sumOf { it.toByteArray().size } > 120000 ||
                        mode !in setOf("python_syntax", "python_tests", "javascript", "javascript_tests")) {
                        result.error("invalid_project", "Некорректный проект проверки.", null); return@setMethodCallHandler
                    }
                    pending = result
                    try {
                        start(JSONObject().put("files", JSONObject(files)).put("mode", mode),
                            (call.argument<Number>("timeout_ms")?.toLong() ?: 60000).coerceIn(1000, 60000))
                    } catch (_: Exception) {
                        finish(JSONObject().put("exit_code", 1).put("output", "Среда проверки на телефоне недоступна."))
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun resource(uri: Uri): WebResourceResponse {
        val path = uri.path.orEmpty().removePrefix("/development/")
        val allowed = setOf("index.html", "runner.js", "worker.js", "pyodide/pyodide.js",
            "pyodide/pyodide.asm.js", "pyodide/pyodide.asm.wasm", "pyodide/python_stdlib.zip", "pyodide/pyodide-lock.json")
        if (uri.scheme != "https" || uri.host != "troika.invalid" || uri.query != null || path !in allowed) {
            return WebResourceResponse("text/plain", "UTF-8", 403, "Blocked", emptyMap(), ByteArrayInputStream(ByteArray(0)))
        }
        val mime = when { path.endsWith(".wasm") -> "application/wasm"; path.endsWith(".js") -> "text/javascript"
            path.endsWith(".json") -> "application/json"; path.endsWith(".zip") -> "application/zip"; else -> "text/html" }
        return WebResourceResponse(mime, "UTF-8", 200, "OK", mapOf(
            "Content-Security-Policy" to "default-src 'none'; script-src 'self' 'unsafe-eval'; worker-src 'self'; connect-src 'self';",
            "Cache-Control" to "no-store"), activity.assets.open("development/$path"))
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun start(payload: JSONObject, duration: Long) {
        val web = WebView(activity)
        view = web
        with(web.settings) {
            javaScriptEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            blockNetworkLoads = true
            domStorageEnabled = false
            javaScriptCanOpenWindowsAutomatically = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }
        // Python/JS output belongs only in the bounded report, never Logcat.
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(message: ConsoleMessage?) = true
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(v: WebView?, request: WebResourceRequest): WebResourceResponse = resource(request.url)
            override fun shouldOverrideUrlLoading(v: WebView?, request: WebResourceRequest) = true
            override fun onPageFinished(v: WebView?, url: String?) {
                if (pending == null || view !== web) return
                web.evaluateJavascript("startCheck($payload)", null)
                val waiter = object : Runnable {
                    override fun run() {
                        if (pending == null || view !== web) return
                        web.evaluateJavascript("JSON.stringify(window.checkResult)") { encoded ->
                            if (pending == null || view !== web) return@evaluateJavascript
                            try {
                                val value = org.json.JSONTokener(encoded).nextValue()
                                if (value is String && value != "null") { finish(JSONObject(value)); return@evaluateJavascript }
                            } catch (_: Exception) {}
                            handler.postDelayed(this, 100)
                        }
                    }
                }
                poll = waiter
                handler.post(waiter)
            }
            override fun onRenderProcessGone(v: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                finish(JSONObject().put("exit_code", 1).put("output", "Среда проверки остановилась."))
                return true
            }
        }
        timeout = Runnable { finish(JSONObject().put("exit_code", -1).put("output", "Проверка остановлена по времени.").put("timed_out", true)) }
        handler.postDelayed(timeout!!, duration)
        web.loadUrl("https://troika.invalid/development/index.html")
    }

    private fun finish(report: JSONObject) {
        val result = pending ?: return
        pending = null
        timeout?.let(handler::removeCallbacks)
        poll?.let(handler::removeCallbacks)
        val web = view
        view = null
        web?.evaluateJavascript("stopCheck()", null)
        web?.destroy()
        result.success(mapOf("exit_code" to report.optInt("exit_code", 1),
            "output" to report.optString("output").take(32000),
            "no_tests" to report.optBoolean("no_tests"),
            "timed_out" to report.optBoolean("timed_out"), "cancelled" to report.optBoolean("cancelled")))
    }
}
