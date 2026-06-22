package com.troika.hermes_assistant

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread
import kotlin.math.sqrt

/**
 * Параллельный микрофонный монитор для barge-in (перебить Тройку голосом).
 *
 * Главная проблема старой версии: фиксированный порог 700 требовал кричать,
 * потому что качество AEC и громкость динамика у разных телефонов разные —
 * фоновое эхо своего же TTS «съедало» запас до порога.
 *
 * Новый подход — АДАПТИВНЫЙ порог:
 *   1. grace (~250мс) — динамик/AEC раскачиваются, игнор.
 *   2. калибровка (~350мс) — меряем уровень остаточного эхо TTS (фон).
 *   3. детект — срабатываем когда громкость превышает max(фон×множитель, минимум)
 *      несколько кадров подряд. Это ловит обычную речь поверх любого фона и не
 *      зависит от абсолютной громкости.
 *
 * Метрика — RMS (корень из средней энергии): лучше отделяет речь от ровного
 * эхо-фона, чем средняя |амплитуда|.
 */
class BargeInMonitor(
    // floorThreshold — абсолютный минимум, ниже которого никогда не триггерим
    // (защита от тишины). При наличии фона реальный порог считается адаптивно.
    private val floorThreshold: Int = 500,
    private val sampleRate: Int = 16000,
    private val frameMs: Int = 20,
    private val consecutiveFrames: Int = 3,
    private val gracePeriodMs: Long = 250,
    private val calibrationMs: Long = 350,
    // во сколько раз голос должен превышать эхо-фон, чтобы считаться речью юзера
    private val overBackgroundFactor: Double = 2.2,
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

                val startTime = System.currentTimeMillis()
                val buf = ShortArray(frameSize)
                var loud = 0

                // Калибровка эхо-фона: копим RMS кадров и берём «спокойный»
                // уровень (среднее) как базу. Адаптивный порог = база × фактор.
                var bgSum = 0.0
                var bgCount = 0
                var dynamicThreshold = floorThreshold

                while (running.get()) {
                    val read = rec.read(buf, 0, buf.size)
                    if (read <= 0) {
                        Thread.sleep(3)
                        continue
                    }
                    val now = System.currentTimeMillis()
                    val elapsed = now - startTime
                    if (elapsed < gracePeriodMs) continue

                    // RMS кадра
                    var energy = 0.0
                    for (i in 0 until read) {
                        val s = buf[i].toInt()
                        energy += (s * s).toDouble()
                    }
                    val rms = sqrt(energy / read)

                    // Фаза калибровки — измеряем фон, не триггерим.
                    if (elapsed < gracePeriodMs + calibrationMs) {
                        bgSum += rms
                        bgCount++
                        continue
                    } else if (bgCount > 0 && dynamicThreshold == floorThreshold) {
                        val bg = bgSum / bgCount
                        dynamicThreshold =
                            (bg * overBackgroundFactor).toInt().coerceAtLeast(floorThreshold)
                        Log.d(tag, "calibrated: bg=${bg.toInt()} threshold=$dynamicThreshold")
                    }

                    if (rms > dynamicThreshold) {
                        loud++
                        if (loud >= consecutiveFrames && triggered.compareAndSet(false, true)) {
                            Log.i(tag, "barge-in detected (rms=${rms.toInt()} thr=$dynamicThreshold)")
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
