package com.troika.hermes_assistant

/** Serializes refreshes without holding the credential store during network I/O. */
internal class AccountSessionRefresh<I>(
    private val store: Store<I>,
    private val request: (State<I>) -> Result,
    private val now: () -> Long = System::currentTimeMillis,
) {
    data class State<I>(
        val identity: I,
        val accessToken: String,
        val refreshToken: String,
        val expiresAtMillis: Long,
    )

    data class Tokens(
        val accessToken: String,
        val refreshToken: String,
        val expiresAtMillis: Long,
        val sessionId: String,
    )

    sealed class Result {
        data class Success(val tokens: Tokens) : Result()
        object Rejected : Result()
        object Unavailable : Result()
    }

    interface Store<I> {
        fun read(): State<I>?
        fun publish(expected: State<I>, tokens: Tokens): Boolean
        fun reject(expected: State<I>)
    }

    private val refreshLock = Any()

    fun accessToken(identity: I, force: Boolean = false, rejectedToken: String? = null): String {
        val observed = store.read()?.takeIf { it.identity == identity } ?: return ""
        if (!observed.accessToken.startsWith("trk_live_")) return observed.accessToken
        if (!force && fresh(observed)) return observed.accessToken
        return synchronized(refreshLock) {
            val state = store.read()?.takeIf { it.identity == identity } ?: return@synchronized ""
            // A concurrent caller may already have replaced the rejected credential.
            val rejected = rejectedToken ?: observed.accessToken
            if (state.accessToken != rejected || (!force && fresh(state))) return@synchronized state.accessToken
            when (val result = request(state)) {
                is Result.Success -> if (store.publish(state, result.tokens)) result.tokens.accessToken else ""
                Result.Rejected -> { store.reject(state); "" }
                Result.Unavailable -> ""
            }
        }
    }

    private fun fresh(state: State<I>) = state.expiresAtMillis > now() + 300_000L
}
