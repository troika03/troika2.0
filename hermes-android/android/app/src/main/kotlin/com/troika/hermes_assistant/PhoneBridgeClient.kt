package com.troika.hermes_assistant

import android.content.Context
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * WebSocket-клиент для связи с Hermes PC.
 * Получает команды от LLM и передаёт их на исполнение в [PhoneCommandExecutor].
 *
 * Подключение восстанавливается автоматически с экспоненциальным backoff.
 */
class PhoneBridgeClient(
    private val ctx: Context,
    private val serverUrl: String,   // http://host:port
    private val apiKey: String,
) {
    private val tag = "PhoneBridge"
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)  // ws keep-alive
        .writeTimeout(120, TimeUnit.SECONDS)     // большие base64 файлы
        .connectTimeout(15, TimeUnit.SECONDS)
        .build()

    private var ws: WebSocket? = null
    private val isRunning = AtomicBoolean(false)
    private var reconnectDelayMs = 2000L
    private val maxReconnectDelayMs = 60_000L

    fun start() {
        if (!isRunning.compareAndSet(false, true)) return
        connect()
    }

    fun stop() {
        isRunning.set(false)
        ws?.close(1000, "stop")
        ws = null
    }

    private fun connect() {
        if (!isRunning.get()) return

        val wsUrl = serverUrl.replaceFirst("http", "ws").trimEnd('/') + "/v1/phone/commands"
        Log.i(tag, "WS connecting")

        val req = Request.Builder()
            .url(wsUrl)
            .header("Authorization", "Bearer $apiKey")
            .build()

        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(tag, "WS connected")
                reconnectDelayMs = 2000L  // сброс backoff
                // Сообщаем серверу что мы готовы
                webSocket.send(JSONObject(mapOf(
                    "event" to "phone_ready",
                    "model" to android.os.Build.MODEL,
                    "android" to android.os.Build.VERSION.SDK_INT,
                )).toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(tag, "WS command received")
                handleCommand(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(tag, "WS closing code=$code")
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(tag, "WS closed code=$code")
                scheduleReconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(tag, "WS transport failed")
                scheduleReconnect()
            }
        })
    }

    private fun scheduleReconnect() {
        if (!isRunning.get()) return
        val delay = reconnectDelayMs
        reconnectDelayMs = (reconnectDelayMs * 2).coerceAtMost(maxReconnectDelayMs)
        Thread {
            Thread.sleep(delay)
            if (isRunning.get()) connect()
        }.start()
    }

    private fun handleCommand(raw: String) {
        try {
            val msg = JSONObject(raw)
            val id = msg.optString("id", "")
            val action = msg.optString("action", "")
            val params = msg.optJSONObject("params") ?: JSONObject()

            // Выполняем команду в фоне, отвечаем когда готово
            Thread {
                val result = try {
                    PhoneCommandExecutor.execute(ctx, action, params)
                } catch (e: Exception) {
                    Log.e(tag, "Command execution failed")
                    JSONObject().apply {
                        put("ok", false)
                        put("error", "executor_failed")
                    }
                }
                val response = JSONObject().apply {
                    put("id", id)
                    put("result", result)
                }
                ws?.send(response.toString())
            }.start()
        } catch (e: Exception) {
            Log.e(tag, "Command JSON invalid")
        }
    }
}
