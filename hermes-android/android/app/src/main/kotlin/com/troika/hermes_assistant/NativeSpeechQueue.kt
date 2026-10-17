package com.troika.hermes_assistant

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.Executors
import java.util.concurrent.Future

/** Plays complete phrases while the network is still producing the reply. */
class NativeSpeechQueue(
    private val speak: (String, () -> Unit) -> Unit,
    private val shouldStop: () -> Boolean,
    private val prepare: ((String) -> ByteArray?)? = null,
    private val playPrepared: ((ByteArray, () -> Unit) -> Unit)? = null,
) {
    private data class Phrase(val text: String, val audio: Future<ByteArray?>?)
    private val lock = Object()
    private val pending = ArrayDeque<String>()
    private val ready = ArrayDeque<Phrase>()
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
                while (!cancelled && !shouldStop()) {
                    val phrase = synchronized(lock) {
                        prefetch()
                        while (ready.isEmpty() && !closed && !cancelled && !shouldStop()) { lock.wait(100); prefetch() }
                        if (cancelled || shouldStop() || (closed && ready.isEmpty())) null
                        else ready.removeFirstOrNull()?.also { prefetch() }
                    } ?: if (closed || cancelled) break else continue
                    if (shouldStop()) break
                    val audio = try { phrase.audio?.get(12, TimeUnit.SECONDS) } catch (_: Exception) { null }
                    try {
                        if (cancelled || shouldStop()) break
                        val done = CountDownLatch(1)
                        if (prepare == null) speak(phrase.text) { done.countDown() }
                        else if (audio != null && playPrepared != null) playPrepared.invoke(audio) { done.countDown() }
                        else continue
                        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(90)
                        while (!done.await(100, TimeUnit.MILLISECONDS)) {
                            if (cancelled || shouldStop() || System.nanoTime() >= deadline) return@Thread
                        }
                    } finally { audio?.fill(0) }
                }
            } finally { cancelPrepared(); pool?.shutdownNow(); completed.countDown() }
        }.apply { name = "TroikaReplySpeech"; isDaemon = true }.start()
    }

    fun add(delta: String) = synchronized(lock) {
        if (closed || cancelled) return@synchronized
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

    private fun prefetch() {
        while (!cancelled && ready.size < 2 && pending.isNotEmpty()) {
            val text = pending.removeFirst()
            val audio = pool?.submit<ByteArray?> {
                val result = try { prepare?.invoke(text) } catch (_: Exception) { null }
                if (cancelled || shouldStop()) { result?.fill(0); null } else result
            }
            ready.addLast(Phrase(text, audio))
        }
    }

    private fun cancelPrepared() = synchronized(lock) {
        cancelled = true
        ready.forEach { phrase ->
            val future = phrase.audio
            if (future != null && future.isDone && !future.isCancelled) {
                try { future.get()?.fill(0) } catch (_: Exception) {}
            }
            future?.cancel(true)
        }
        ready.clear()
    }

    private fun enqueue(text: String) {
        val clean = text.replace(Regex("[*#`]"), "").trim()
        if (clean.isNotEmpty() && pending.size < 100) pending.addLast(clean)
    }

    fun finish() {
        synchronized(lock) { enqueue(buffer); buffer = ""; closed = true; prefetch(); lock.notifyAll() }
        if (!completed.await(120, TimeUnit.SECONDS)) cancel()
    }

    fun cancel() = synchronized(lock) {
        cancelled = true; pending.clear(); buffer = ""; cancelPrepared(); lock.notifyAll()
    }
}
