package com.troika.hermes_assistant

/** Serializes background recognition attempts without retaining audio or text. */
internal class WakeRecognitionLifecycle {
    enum class Failure { NO_SPEECH, BUSY, AUDIO, TRANSIENT, PERMISSION, UNAVAILABLE }

    private var generation = 0L
    private var pending = false
    private var active = false
    private var blocked = false
    private var failures = 0

    @Synchronized
    fun schedule(): Long? {
        if (pending || active || blocked) return null
        generation++
        pending = true
        return generation
    }

    @Synchronized
    fun start(ticket: Long): Boolean {
        if (ticket != generation || !pending || blocked) return false
        pending = false
        active = true
        return true
    }

    @Synchronized
    fun isCurrent(ticket: Long): Boolean = ticket == generation && active

    /** Null means either an obsolete callback or an error requiring user action. */
    @Synchronized
    fun complete(ticket: Long, failure: Failure = Failure.NO_SPEECH): Long? {
        if (!isCurrent(ticket)) return null
        active = false
        if (failure == Failure.PERMISSION || failure == Failure.UNAVAILABLE) {
            blocked = true
            return null
        }
        if (failure == Failure.NO_SPEECH) {
            failures = 0
            return 800L
        }
        failures = (failures + 1).coerceAtMost(6)
        val base = when (failure) {
            Failure.BUSY -> 1500L
            Failure.AUDIO -> 2000L
            else -> 1000L
        }
        return (base * (1L shl (failures - 1))).coerceAtMost(30_000L)
    }

    /** Pause/stop invalidate both a delayed start and every callback of its recognizer. */
    @Synchronized
    fun invalidate() {
        generation++
        pending = false
        active = false
    }

    /** A fresh explicit service start may retry a previously unavailable recognizer. */
    @Synchronized
    fun retryAfterExplicitStart() {
        if (blocked) {
            blocked = false
            failures = 0
        }
    }
}
