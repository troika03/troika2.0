package com.troika.hermes_assistant

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** One native credential owner for Flutter, background voice and reminders. */
object NativeAccountSession {
    const val IDENTITY_REVISION = "flutter.troika_native_identity_revision"
    private const val EMAIL = "flutter.troika_account_email"
    private const val EXPIRY = "flutter.troika_access_token_expires_at"
    private var refresher: AccountSessionRefresh<Identity>? = null

    /** Token rotation preserves identity; logout and replacement invalidate it. */
    data class Identity internal constructor(
        val serverUrl: String,
        val owner: String,
        val sessionKey: String,
        val sessionId: String,
        val generation: Long,
    )

    /** Event ownership also covers local commands and manually configured gateways. */
    data class EventIdentity internal constructor(
        val serverUrl: String,
        val owner: String,
        val sessionKey: String,
        val sessionId: String,
        val generation: Long,
        val signedIn: Boolean,
        internal val accountIdentity: Identity?,
    )

    fun eventSnapshot(context: Context): EventIdentity = synchronized(SecureTokenStore) {
        val prefs = preferences(context)
        val owner = prefs.getString(EMAIL, "").orEmpty().trim().lowercase()
        EventIdentity(value(prefs, "server_url").trimEnd('/'), owner,
            value(prefs, "session_key"), value(prefs, "session_id"),
            prefs.getLong(IDENTITY_REVISION, 0),
            owner.isNotEmpty() && value(prefs, "api_key").startsWith("trk_live_"), snapshot(context))
    }

    fun currentEvent(context: Context, identity: EventIdentity): Boolean = eventSnapshot(context) == identity

    fun snapshot(context: Context, requestedServerUrl: String? = null): Identity? = synchronized(SecureTokenStore) {
        val prefs = preferences(context)
        val origin = value(prefs, "server_url").trimEnd('/')
        if (origin.isBlank() || value(prefs, "api_key").isBlank() ||
            (requestedServerUrl != null && origin != requestedServerUrl.trim().trimEnd('/'))) return@synchronized null
        Identity(origin, prefs.getString(EMAIL, "").orEmpty().trim(),
            value(prefs, "session_key"), value(prefs, "session_id"), prefs.getLong(IDENTITY_REVISION, 0))
    }

    fun current(context: Context, identity: Identity): Boolean = snapshot(context) == identity

    fun accessToken(context: Context, serverUrl: String, force: Boolean = false): String {
        val identity = snapshot(context, serverUrl) ?: return ""
        return accessToken(context, identity, force)
    }

    fun accessToken(context: Context, identity: Identity, force: Boolean = false, rejectedToken: String? = null): String =
        coordinator(context.applicationContext).accessToken(identity, force, rejectedToken)

    @Synchronized private fun coordinator(context: Context): AccountSessionRefresh<Identity> {
        refresher?.let { return it }
        return AccountSessionRefresh(object : AccountSessionRefresh.Store<Identity> {
            override fun read() = synchronized(SecureTokenStore) { readState(context) }
            override fun publish(expected: AccountSessionRefresh.State<Identity>, tokens: AccountSessionRefresh.Tokens) =
                synchronized(SecureTokenStore) {
                    if (readState(context) != expected) return@synchronized false
                    saveAccount(context, expected.identity.owner, tokens.accessToken, tokens.refreshToken,
                        tokens.expiresAtMillis, tokens.sessionId)
                }
            override fun reject(expected: AccountSessionRefresh.State<Identity>) {
                val rejected = synchronized(SecureTokenStore) {
                    if (readState(context) != expected) null else invalidate(context, "revoke").second
                }
                if (rejected != null) NativeReminderDelivery.clear(context, rejected)
            }
        }, ::request).also { refresher = it }
    }

    private fun readState(context: Context): AccountSessionRefresh.State<Identity>? {
        val identity = snapshot(context) ?: return null
        val prefs = preferences(context)
        return AccountSessionRefresh.State(identity, value(prefs, "api_key"),
            SecureTokenStore.get(context, binding(identity)).orEmpty(), prefs.getLong(EXPIRY, 0))
    }

    /** Publish all Android account preferences together after encryption succeeds. */
    fun saveAccount(context: Context, email: String, token: String, refreshToken: String,
                    expiresAtMillis: Long, sessionId: String, replaceIdentity: Boolean = false,
                    expectedGeneration: Long? = null): Boolean = synchronized(SecureTokenStore) {
        val prefs = preferences(context)
        if (expectedGeneration != null && expectedGeneration != prefs.getLong(IDENTITY_REVISION, 0)) return@synchronized false
        val origin = value(prefs, "server_url").trimEnd('/')
        if (origin.isBlank() || !token.startsWith("trk_live_") || !refreshToken.startsWith("trk_refresh_") ||
            expiresAtMillis <= 0 || !sessionId.startsWith("ses_")) return@synchronized false
        val previous = snapshot(context)
        val owner = email.trim().lowercase()
        val changesIdentity = replaceIdentity || previous == null || previous.owner != owner ||
            previous.sessionKey != sessionId || previous.sessionId != sessionId
        val generation = prefs.getLong(IDENTITY_REVISION, 0) + if (changesIdentity) 1 else 0
        val identity = Identity(origin, owner, sessionId, sessionId, generation)
        if (!SecureTokenStore.put(context, refreshToken, binding(identity))) return@synchronized false
        prefs.edit().putString(EMAIL, owner)
            .putCompat("api_key", token).putCompat("session_key", sessionId).putCompat("session_id", sessionId)
            .putLong(EXPIRY, expiresAtMillis).putLong(IDENTITY_REVISION, generation).commit()
    }

    /** Invalidate the identity without waiting for an in-flight network request. */
    fun clear(context: Context, expectedGeneration: Long? = null, mode: String = "signout"): Boolean {
        val (saved, generation) = synchronized(SecureTokenStore) {
            if (expectedGeneration != null && preferences(context).getLong(IDENTITY_REVISION, 0) != expectedGeneration) return false
            require(mode in setOf("signout", "revoke", "delete"))
            invalidate(context, mode)
        }
        NativeReminderDelivery.clear(context, generation)
        return saved
    }

    private fun invalidate(context: Context, mode: String = "signout"): Pair<Boolean, Long> {
        val prefs = preferences(context)
        val generation = prefs.getLong(IDENTITY_REVISION, 0) + 1
        val editor = prefs.edit().remove(EMAIL).remove(EXPIRY).removeCompat("api_key")
            .putLong(IDENTITY_REVISION, generation)
            .putBoolean("flutter.troika_phone_control_enabled", false)
            .putBoolean("flutter.hermes_phone_control_enabled", false)
        if (mode != "signout") {
            for (name in listOf("wake_word_enabled", "location_context_enabled")) {
                editor.putBoolean("flutter.troika_$name", false).putBoolean("flutter.hermes_$name", false)
            }
            if (mode == "delete") {
                editor.removeCompat("session_key").removeCompat("session_id")
                    .putBoolean("flutter.troika_onboarding_done", false).putBoolean("flutter.hermes_onboarding_done", false)
            } else {
                val session = "mobile-" + java.util.UUID.randomUUID().toString()
                editor.putCompat("session_key", session).putCompat("session_id", session)
            }
        }
        val saved = editor.commit()
        SecureTokenStore.clear(context)
        return saved to generation
    }

    fun setServerUrl(context: Context, serverUrl: String): Boolean {
        var changed = false
        var generation = 0L
        val saved = synchronized(SecureTokenStore) {
            val prefs = preferences(context)
            changed = value(prefs, "server_url").trimEnd('/') != serverUrl.trim().trimEnd('/')
            generation = prefs.getLong(IDENTITY_REVISION, 0) + if (changed) 1 else 0
            val editor = prefs.edit().putCompat("server_url", serverUrl)
            if (changed) {
                SecureTokenStore.clear(context)
                editor.remove(EMAIL).remove(EXPIRY).removeCompat("api_key")
                    .putLong(IDENTITY_REVISION, generation)
            }
            editor.commit()
        }
        if (changed) NativeReminderDelivery.clear(context, generation)
        return saved
    }

    fun setApiKey(context: Context, token: String): Boolean {
        var changed = false
        var generation = 0L
        val saved = synchronized(SecureTokenStore) {
            val prefs = preferences(context)
            changed = value(prefs, "api_key") != token.trim()
            generation = prefs.getLong(IDENTITY_REVISION, 0) + if (changed) 1 else 0
            if (changed) SecureTokenStore.clear(context)
            val editor = prefs.edit().putCompat("api_key", token.trim())
            if (changed) editor.remove(EXPIRY).putLong(IDENTITY_REVISION, generation)
            editor.commit()
        }
        if (changed) NativeReminderDelivery.clear(context, generation)
        return saved
    }

    private fun request(state: AccountSessionRefresh.State<Identity>): AccountSessionRefresh.Result {
        val legacy = state.refreshToken.isBlank()
        val path = if (legacy) "/v1/auth/upgrade-token" else "/v1/auth/refresh"
        var connection: HttpURLConnection? = null
        return try {
            connection = URL(state.identity.serverUrl + path).openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = 8000
            connection.readTimeout = 20000
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Content-Type", "application/json")
            if (legacy) connection.setRequestProperty("Authorization", "Bearer ${state.accessToken}")
            val body = if (legacy) JSONObject() else JSONObject().put("refresh_token", state.refreshToken)
            connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            when (connection.responseCode) {
                401 -> AccountSessionRefresh.Result.Rejected
                200 -> {
                    val bytes = connection.inputStream.use { it.readBytesLimited(64 * 1024) }
                    val data = JSONObject(String(bytes, Charsets.UTF_8))
                    val access = data.optString("access_token", data.optString("token"))
                    val refresh = data.optString("refresh_token")
                    val session = data.optString("home_session_id")
                    val expires = data.optDouble("access_expires_at", 0.0)
                    if (!access.startsWith("trk_live_") || !refresh.startsWith("trk_refresh_") ||
                        !session.startsWith("ses_") || !expires.isFinite() || expires <= 0 || expires > Long.MAX_VALUE / 1000.0) {
                        AccountSessionRefresh.Result.Unavailable
                    } else AccountSessionRefresh.Result.Success(AccountSessionRefresh.Tokens(access, refresh, (expires * 1000).toLong(), session))
                }
                else -> AccountSessionRefresh.Result.Unavailable
            }
        } catch (_: Exception) {
            AccountSessionRefresh.Result.Unavailable
        } finally { connection?.disconnect() }
    }

    private fun java.io.InputStream.readBytesLimited(limit: Int): ByteArray {
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (true) {
            val count = read(buffer)
            if (count < 0) return output.toByteArray()
            require(output.size() + count <= limit)
            output.write(buffer, 0, count)
        }
    }

    private fun binding(identity: Identity) = listOf(identity.serverUrl, identity.owner, identity.sessionKey, identity.sessionId).joinToString("\n")
    private fun preferences(context: Context) = context.getSharedPreferences(HermesListenerService.PREFS, Context.MODE_PRIVATE)
    private fun value(prefs: SharedPreferences, name: String) =
        (prefs.getString("flutter.troika_$name", null) ?: prefs.getString("flutter.hermes_$name", null)).orEmpty().trim()
    private fun SharedPreferences.Editor.putCompat(name: String, value: String): SharedPreferences.Editor =
        putString("flutter.troika_$name", value).putString("flutter.hermes_$name", value)
    private fun SharedPreferences.Editor.removeCompat(name: String): SharedPreferences.Editor =
        remove("flutter.troika_$name").remove("flutter.hermes_$name")
}
