package com.troika.hermes_assistant

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Параллельный микрофонный монитор для barge-in:
 * во время TTS слушает микрофон через отдельный AudioRecord (с AEC чтобы
 * не цеплять свой же динамик), считает амплитуду, и если 3 кадра подряд
 * превышают порог — дергает onUserStarted. После этого монитор больше
 * не срабатывает в текущей сессии — start() новый цикл нужен явно.
 *
 * grace-период (~500ms) в начале — чтобы первый звук динамика не оборвал сам себя.
 */
class BargeInMonitor(
    private val threshold: Int = 1200,
    private val sampleRate: Int = 16000,
    private val frameMs: Int = 30,
    private val consecutiveFrames: Int = 2,
    private val gracePeriodMs: Long = 300,
    private val onUserStarted: () -> Unit,
) {
    private val tag = "BargeIn"
    private val running = AtomicBoolean(false)
    private val triggered = AtomicBoolean(false)
    private var monitorThread: Thread? = null
    private var record: AudioRecord? = null
    private var aec: AcousticEchoCanceler? = null
    private var ns: NoiseSuppressor? = null

    fun start() {
        if (!running.compareAndSet(false, true)) return
        triggered.set(false)

        monitorThread = thread(name = "BargeInMonitor") {
            val frameSize = (sampleRate * frameMs / 1000).coerceAtLeast(160)
            val minBuf = AudioRecord.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            ).coerceAtLeast(frameSize * 4)

            var rec: AudioRecord? = null
            try {
                rec = AudioRecord(
                    MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                    sampleRate,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    minBuf,
                )
                if (rec.state != AudioRecord.STATE_INITIALIZED) {
                    Log.w(tag, "AudioRecord init failed")
                    return@thread
                }
                record = rec

                attachEffects(rec.audioSessionId)
                rec.startRecording()
                Log.d(tag, "started, threshold=$threshold grace=${gracePeriodMs}ms")

                val startTime = System.currentTimeMillis()
                val buf = ShortArray(frameSize)
                var loud = 0

                while (running.get()) {
                    val read = rec.read(buf, 0, buf.size)
                    if (read <= 0) {
                        Thread.sleep(5)
                        continue
                    }
                    if (System.currentTimeMillis() - startTime < gracePeriodMs) continue

                    var sum = 0L
                    for (i in 0 until read) sum += Math.abs(buf[i].toInt())
                    val amp = (sum / read).toInt()

                    if (amp > threshold) {
                        loud++
                        if (loud >= consecutiveFrames && triggered.compareAndSet(false, true)) {
                            Log.i(tag, "barge-in detected (amp=$amp)")
                            running.set(false)
                            try { onUserStarted() } catch (e: Exception) {
                                Log.e(tag, "callback error: ${e.message}")
                            }
                            break
                        }
                    } else {
                        loud = 0
                    }
                }
            } catch (e: SecurityException) {
                Log.w(tag, "no mic permission: ${e.message}")
            } catch (e: Exception) {
                Log.e(tag, "monitor error: ${e.message}", e)
            } finally {
                releaseEffects()
                try { rec?.stop() } catch (_: Exception) {}
                try { rec?.release() } catch (_: Exception) {}
                record = null
            }
        }
    }

    fun stop() {
        running.set(false)
        try { monitorThread?.join(500) } catch (_: Exception) {}
        monitorThread = null
    }

    fun wasTriggered(): Boolean = triggered.get()

    private fun attachEffects(sessionId: Int) {
        if (AcousticEchoCanceler.isAvailable()) {
            try {
                aec = AcousticEchoCanceler.create(sessionId)?.also { it.enabled = true }
            } catch (e: Exception) { Log.w(tag, "AEC failed: ${e.message}") }
        }
        if (NoiseSuppressor.isAvailable()) {
            try {
                ns = NoiseSuppressor.create(sessionId)?.also { it.enabled = true }
            } catch (e: Exception) { Log.w(tag, "NS failed: ${e.message}") }
        }
    }

    private fun releaseEffects() {
        try { aec?.release() } catch (_: Exception) {}
        try { ns?.release() } catch (_: Exception) {}
        aec = null
        ns = null
    }
}
