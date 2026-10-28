package com.troika.hermes_assistant

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Plays complete phrases while the network is still producing the reply. */
class NativeSpeechQueue(
    private val speak: (String, () -> Unit) -> Unit,
    private val shouldStop: () -> Boolean,
    private val prepare: ((String) -> PreparedAudio?)? = null,
    private val playPrepared: ((PreparedAudio, () -> Unit) -> Unit)? = null,
    private val preparationTimeoutMs: Long = 12_000,
    private val playbackTimeoutMs: Long = 90_000,
) {
    /** Returned before EOF; close must stop this handle's fetch/player and wake readers. */
    interface PreparedAudio : AutoCloseable

    private class Phrase(val text: String, var prepared: Boolean) {
        var audio: PreparedAudio? = null
        var discarded = false
    }

    private val lock = Object()
    private val pending = ArrayDeque<String>()
    private val ready = ArrayDeque<Phrase>()
    private var active: Phrase? = null
    private val pool = if (prepare == null) null else Executors.newFixedThreadPool(2) { task ->
        Thread(task, "TroikaVoicePrepare").apply { isDaemon = true }
    }
    private val completed = CountDownLatch(1)
    private var buffer = ""
    private var closed = false
    @Volatile private var cancelled = false
    private val boundary = Regex("""[!?…](?:\s|$)|\.\s|\n""")

    init {
        Thread {
            try {
                while (true) {
                    val phrase = synchronized(lock) {
                        prefetch()
                        while (ready.isEmpty() && !closed && !cancelled && !shouldStop()) {
                            lock.wait(100)
                            prefetch()
                        }
                        if (cancelled || shouldStop() || (closed && ready.isEmpty())) null
                        else ready.removeFirstOrNull()?.also { active = it; prefetch() }
                    } ?: break
                    try {
                        val audio = awaitPrepared(phrase)
                        val done = CountDownLatch(1)
                        // These callbacks must return promptly. Dispatch and cancel share the
                        // lock so cancel cannot return before a new playback dispatch starts.
                        val started = synchronized(lock) {
                            if (cancelled || shouldStop() || phrase.discarded) false
                            else if (prepare == null) {
                                speak(phrase.text) { done.countDown() }
                                true
                            } else if (audio != null && playPrepared != null) {
                                playPrepared.invoke(audio) { done.countDown() }
                                true
                            } else false
                        }
                        if (!started) continue
                        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(playbackTimeoutMs)
                        while (!done.await(100, TimeUnit.MILLISECONDS)) {
                            if (cancelled || shouldStop() || System.nanoTime() >= deadline) return@Thread
                        }
                    } finally { release(phrase) }
                }
            } finally {
                cancel()
                pool?.shutdownNow()
                completed.countDown()
            }
        }.apply { name = "TroikaReplySpeech"; isDaemon = true }.start()
    }

    fun add(delta: String) = synchronized(lock) {
        if (closed || cancelled || shouldStop()) return@synchronized
        buffer += delta
        if (buffer.trimStart().startsWith("[emo:") && !buffer.contains(']')) return@synchronized
        buffer = buffer.replace(Regex("""\[emo:\s*[^\]]*]"""), "")
        while (buffer.isNotEmpty()) {
            val found = boundary.find(buffer)
            var cut = found?.range?.last?.plus(1) ?: 0
            if (cut == 0 && buffer.length > 180) cut = buffer.lastIndexOf(' ', 180).takeIf { it > 0 } ?: 180
            if (cut == 0) break
            enqueue(buffer.substring(0, cut))
            buffer = buffer.substring(cut)
        }
        lock.notifyAll()
        prefetch()
    }

    /** Called only with lock held; at most two phrases wait ahead of the active one. */
    private fun prefetch() {
        while (!cancelled && !shouldStop() && ready.size < 2 && pending.isNotEmpty()) {
            val phrase = Phrase(pending.removeFirst(), prepare == null)
            ready.addLast(phrase)
            pool?.execute {
                val wanted = synchronized(lock) { !cancelled && !phrase.discarded && !shouldStop() }
                if (!wanted) return@execute
                val result = try { prepare?.invoke(phrase.text) } catch (_: Exception) { null }
                val accepted = synchronized(lock) {
                    if (cancelled || phrase.discarded || shouldStop()) false
                    else {
                        phrase.audio = result
                        phrase.prepared = true
                        lock.notifyAll()
                        true
                    }
                }
                // Do not put ownership in a cancelled Future: a late return must be closed.
                if (!accepted) closeAudio(result)
            }
        }
    }

    private fun awaitPrepared(phrase: Phrase): PreparedAudio? = synchronized(lock) {
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(preparationTimeoutMs)
        while (!phrase.prepared && !cancelled && !phrase.discarded && !shouldStop()) {
            val remaining = deadline - System.nanoTime()
            if (remaining <= 0) break
            lock.wait(minOf(100L, TimeUnit.NANOSECONDS.toMillis(remaining).coerceAtLeast(1L)))
        }
        if (!phrase.prepared || cancelled || shouldStop()) {
            phrase.discarded = true
            null
        } else phrase.audio
    }

    private fun release(phrase: Phrase) {
        val audio = synchronized(lock) {
            phrase.discarded = true
            if (active === phrase) active = null
            phrase.audio.also { phrase.audio = null }
        }
        closeAudio(audio)
    }

    private fun closeAudio(audio: PreparedAudio?) {
        try { audio?.close() } catch (_: Exception) {}
    }

    private fun enqueue(text: String) {
        val clean = text.replace(Regex("[*#`]"), "").trim()
        if (clean.isNotEmpty() && pending.size < 100) pending.addLast(clean)
    }

    fun finish() {
        synchronized(lock) {
            if (!cancelled) { enqueue(buffer); buffer = ""; closed = true; prefetch(); lock.notifyAll() }
        }
        if (!completed.await(120, TimeUnit.SECONDS)) cancel()
    }

    fun cancel() {
        val audio = synchronized(lock) {
            cancelled = true
            pending.clear()
            buffer = ""
            val phrases = ready.toMutableList()
            active?.let { phrases.add(it) }
            ready.clear()
            active = null
            val owned = phrases.mapNotNull { phrase ->
                phrase.discarded = true
                phrase.audio.also { phrase.audio = null }
            }
            lock.notifyAll()
            owned
        }
        audio.forEach(::closeAudio)
    }
}
