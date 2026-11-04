package com.troika.hermes_assistant

import java.util.Locale

/** Owns one queued, loading, or recording wake session without retaining audio. */
internal class OfflineWakeState {
    internal class Ticket(val generation: Long)

    private var generation = 0L
    private var current: Ticket? = null
    private var closed = false

    @Synchronized
    fun start(): Ticket? {
        if (closed || current != null) return null
        return Ticket(++generation).also { current = it }
    }

    @Synchronized
    fun isCurrent(ticket: Ticket): Boolean = !closed && current === ticket

    /** Cancels callbacks immediately; recorder cleanup can finish on its worker. */
    @Synchronized
    fun stop(): Ticket? = current.also {
        current = null
        generation++
    }

    /** Delivers at most one terminal event, only for the current session. */
    @Synchronized
    fun finish(ticket: Ticket): Boolean {
        if (!isCurrent(ticket)) return false
        current = null
        return true
    }

    @Synchronized
    fun close(): Ticket? {
        closed = true
        return stop()
    }
}

/** Rejects substrings and unstable partials; unrelated speech resets the candidate. */
internal class OfflineWakeMatcher {
    private var matchingPartials = 0

    fun accept(text: String, final: Boolean): Boolean {
        // Vosk's grammar produces very short text. Reject unexpected output rather
        // than retaining or tokenizing an unbounded transcript.
        if (text.length > 256) {
            matchingPartials = 0
            return false
        }
        val words = text.lowercase(Locale.ROOT).split(Regex("[^а-яё]+"))
        if (words.none { it == "тройка" }) {
            matchingPartials = 0
            return false
        }
        if (final) return true
        matchingPartials++
        return matchingPartials >= 2
    }
}
