package com.troika.hermes_assistant

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Runs on the voice worker; no Flutter engine is needed to install an alarm. */
object NativeReminderDelivery {
    private val generation = java.util.concurrent.atomic.AtomicLong(0)

    @Synchronized fun clear(context: Context, expectedIdentityRevision: Long? = null) {
        if (expectedIdentityRevision != null && context.getSharedPreferences(
                HermesListenerService.PREFS, Context.MODE_PRIVATE).getLong(
                NativeAccountSession.IDENTITY_REVISION, 0) != expectedIdentityRevision) return
        generation.incrementAndGet()
        ReminderScheduler.clear(context)
    }

    fun sync(context: Context, serverUrl: String, accessToken: String): Map<String, Boolean>? {
        if (serverUrl.isBlank() || accessToken.isBlank()) return null
        val identity = NativeAccountSession.snapshot(context, serverUrl) ?: return null
        return sync(context, identity)
    }

    fun sync(context: Context, identity: NativeAccountSession.Identity): Map<String, Boolean>? {
        val (expectedGeneration, ticket) = synchronized(this) {
            val ticket = ReminderScheduler.beginSync(context, identity) ?: return null
            generation.get() to ticket
        }
        return try {
            if (!current(context, identity, expectedGeneration)) return null
            val token = NativeAccountSession.accessToken(context, identity)
            if (token.isBlank() || !current(context, identity, expectedGeneration)) return null
            var response = fetch(context, identity, token, expectedGeneration) ?: return null
            if (response.first == 401) {
                val refreshed = NativeAccountSession.accessToken(context, identity, force = true, rejectedToken = token)
                if (refreshed.isBlank() || !current(context, identity, expectedGeneration)) return null
                response = fetch(context, identity, refreshed, expectedGeneration) ?: return null
            }
            synchronized(this) {
                // A response from an old origin or account cannot restore or erase alarms.
                if (!current(context, identity, expectedGeneration)) return@synchronized null
                when (response.first) {
                    200 -> ReminderScheduler.applySync(context, response.second ?: return@synchronized null, ticket)
                    401 -> {
                        if (ReminderScheduler.rejectSync(context, ticket)) generation.incrementAndGet()
                        null
                    }
                    else -> null
                }
            }
        } catch (_: Exception) {
            // Preserve the last good offline snapshot on temporary network failure.
            null
        }
    }

    private fun current(context: Context, identity: NativeAccountSession.Identity, expectedGeneration: Long): Boolean =
        generation.get() == expectedGeneration && NativeAccountSession.current(context, identity)

    private fun fetch(context: Context, identity: NativeAccountSession.Identity, token: String,
        expectedGeneration: Long): Pair<Int, JSONObject?>? {
        if (!current(context, identity, expectedGeneration)) return null
        val connection = URL("${identity.serverUrl}/v1/assistant/reminders").openConnection() as HttpURLConnection
        return try {
            connection.connectTimeout = 8000
            connection.readTimeout = 15000
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Authorization", "Bearer $token")
            val status = connection.responseCode
            if (!current(context, identity, expectedGeneration)) return null
            val snapshot = if (status == 200) {
                val text = connection.inputStream.bufferedReader(Charsets.UTF_8).use { reader ->
                    val result = StringBuilder()
                    val buffer = CharArray(4096)
                    while (true) {
                        val count = reader.read(buffer)
                        if (count < 0) break
                        require(result.length + count <= 4 * 1024 * 1024)
                        if (!current(context, identity, expectedGeneration)) return null
                        result.append(buffer, 0, count)
                    }
                    result.toString()
                }
                JSONObject(text)
            } else null
            Pair(status, snapshot)
        } finally {
            connection.disconnect()
        }
    }
}
