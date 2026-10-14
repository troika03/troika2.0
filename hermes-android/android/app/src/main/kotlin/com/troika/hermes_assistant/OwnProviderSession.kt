package com.troika.hermes_assistant

import android.content.Context
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/** Personal keys remain in process RAM; remembered mode fails closed on restart. */
object OwnProviderSession {
    @Volatile private var credentials: Map<String, String>? = null
    fun attach(engine: FlutterEngine) {
        MethodChannel(engine.dartExecutor.binaryMessenger, "troika/own_provider").setMethodCallHandler { call, result ->
            when (call.method) {
                "clear" -> { credentials = null; result.success(null) }
                "configure" -> {
                    val args = call.arguments as? Map<*, *>
                    val values = listOf("owner", "provider", "model", "key").associateWith { args?.get(it) as? String ?: "" }
                    if (values.values.any { it.isBlank() } || values["provider"] !in setOf("openrouter", "openai") ||
                        values["key"]!!.length !in 16..512 || values["key"]!!.any { it.isWhitespace() }) {
                        result.error("invalid_personal_api", "Проверь поля личного API.", null)
                    } else { credentials = values; result.success(null) }
                }
                else -> result.notImplemented()
            }
        }
    }
    fun headers(context: Context, brainUrl: String, accountToken: String): Map<String, String> {
        val prefs = context.getSharedPreferences("FlutterSharedPreferences", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("flutter.troika_personal_provider_enabled", false)) return emptyMap()
        val owner = prefs.getString("flutter.troika_personal_provider_owner", "")
        if (owner != prefs.getString("flutter.troika_account_email", "")) return emptyMap()
        val value = credentials ?: throw IllegalStateException("Введи личный API-ключ снова. Ключ Тройки не использован.")
        check(value["owner"] == owner) { "Личный ключ принадлежит другому сеансу." }
        val checkUrl = brainUrl.substringBeforeLast("/v1/chat/completions") + "/v1/subscription"
        val connection = java.net.URL(checkUrl).openConnection() as java.net.HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 8000; connection.readTimeout = 8000
            connection.setRequestProperty("Authorization", "Bearer $accountToken")
            check(connection.responseCode == 200 && org.json.JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
                .getJSONObject("subscription").optBoolean("byok_enabled", false)) { "Сервер не поддерживает личный API. Ключ Тройки не использован." }
        } finally { connection.disconnect() }
        return mapOf("X-Troika-Provider-Key" to value["key"]!!,
            "X-Troika-Provider" to value["provider"]!!, "X-Troika-Provider-Model" to value["model"]!!)
    }
}
