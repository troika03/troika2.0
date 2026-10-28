package com.troika.hermes_assistant

import java.io.IOException
import okhttp3.Call
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicInteger
import android.os.SystemClock
import android.util.Log

/** Owns one synthesis POST; player reopen/seek reads RAM and never repeats it. */
internal class NativeStreamingSpeech(
    private val fetch: (NativeStreamingSpeech) -> Unit,
    private val onClosed: (NativeStreamingSpeech) -> Unit,
) : NativeSpeechQueue.PreparedAudio {
    val buffer = SpeechAudioBuffer()
    private val closed = AtomicBoolean(false)
    private val started = AtomicBoolean(false)
    private val connection = AtomicReference<Call?>(null)
    private val playbackClosed = AtomicReference<(() -> Unit)?>(null)
    private val traceId = NEXT_TRACE.incrementAndGet()
    private val createdAt = SystemClock.elapsedRealtime()
    @Volatile var eofReceived = false
        private set

    fun trace(phase: String, bytes: Int = 0) {
        if (phase == "eof") eofReceived = true
        // Only phase names, counters and durations; never text, audio, URLs or credentials.
        Log.i("TroikaVoiceTiming", "id=$traceId phase=$phase elapsed_ms=${SystemClock.elapsedRealtime() - createdAt} bytes=$bytes eof=$eofReceived")
    }

    fun start() {
        if (!started.compareAndSet(false, true)) return
        Thread {
            try {
                if (!closed.get()) { trace("request"); fetch(this) }
            } catch (_: Exception) {
                buffer.fail(IOException("Speech download failed"))
            } finally {
                connection.getAndSet(null)?.cancel()
            }
        }.apply { name = "TroikaSpeechDownload"; isDaemon = true }.start()
    }

    fun attach(value: Call): Boolean {
        connection.set(value)
        if (!closed.get()) return true
        connection.compareAndSet(value, null)
        value.cancel()
        return false
    }

    fun onPlaybackClose(callback: () -> Unit) {
        playbackClosed.set(callback)
        if (closed.get()) playbackClosed.getAndSet(null)?.invoke()
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        buffer.close()
        connection.getAndSet(null)?.cancel()
        playbackClosed.getAndSet(null)?.invoke()
        onClosed(this)
    }

    companion object { private val NEXT_TRACE = AtomicInteger(0) }
}
