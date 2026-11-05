package com.troika.hermes_assistant

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import androidx.core.content.ContextCompat
import org.json.JSONObject
import org.vosk.Recognizer
import java.io.IOException
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicLong

/** Owns one bounded microphone capture; PCM and transcripts remain in memory. */
internal class OwnerVoiceCapture(private val context: Context) {
    @Volatile private var cancelled = false
    @Volatile private var finish = false
    @Volatile private var recorder: AudioRecord? = null
    val isCancelled: Boolean get() = cancelled

    fun cancel() { cancelled = true; cancellations.incrementAndGet(); try { recorder?.stop() } catch (_: Exception) {} }
    fun finish() { finish = true; try { recorder?.stop() } catch (_: Exception) {} }

    @SuppressLint("MissingPermission")
    fun capture(enrollment: Boolean, current: () -> Boolean): Result? {
        if (!active.compareAndSet(null, this)) throw IOException("Микрофон уже используется")
        var recognizer: Recognizer? = null
        var localRecorder: AudioRecord? = null
        val buffer = ShortArray(3_200)
        try {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                throw SecurityException("Разреши доступ к микрофону")
            }
            val (model, speaker) = OwnerVoiceAssets.models(context)
            if (cancelled || !current()) return null
            recognizer = Recognizer(model, 16_000f).also { it.setSpeakerModel(speaker) }
            val minimum = AudioRecord.getMinBufferSize(16_000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            if (minimum <= 0) throw IOException("Микрофон недоступен")
            localRecorder = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16_000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, 12_800))
            if (localRecorder.state != AudioRecord.STATE_INITIALIZED) throw IOException("Микрофон недоступен")
            recorder = localRecorder
            if (cancelled || !current()) return null
            localRecorder.startRecording()
            if (localRecorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) throw IOException("Микрофон недоступен")
            val started = SystemClock.elapsedRealtime()
            val limit = if (enrollment) 18_000L else 15_000L
            while (!cancelled && !finish && current() && SystemClock.elapsedRealtime() - started < limit) {
                val count = localRecorder.read(buffer, 0, buffer.size)
                if (cancelled || !current()) return null
                if (finish) break
                if (count < 0) throw IOException("Не удалось записать голос")
                if (count == 0) continue
                val final = recognizer.acceptWaveForm(buffer, count)
                buffer.fill(0)
                if (final) {
                    val result = parse(recognizer.result)
                    if (result != null && (result.frames >= OwnerVoicePolicy.MIN_FRAMES || !enrollment)) return result
                    // Enrollment needs a single long phrase; do not mix speakers across pauses.
                    if (result != null) throw IOException("Скажи одну фразу не короче четырёх секунд")
                    recognizer.reset()
                }
            }
            if (cancelled || !current()) return null
            return parse(recognizer.finalResult)
        } finally {
            recorder = null
            try { localRecorder?.stop() } catch (_: Exception) {}
            try { localRecorder?.release() } catch (_: Exception) {}
            try { recognizer?.close() } catch (_: Exception) {}
            buffer.fill(0)
            active.compareAndSet(this, null)
        }
    }

    data class Result(val text: String, val vector: DoubleArray, val frames: Int)
    companion object {
        private val active = AtomicReference<OwnerVoiceCapture?>(null)
        private val cancellations = AtomicLong()
        val cancellationRevision: Long get() = cancellations.get()
        fun cancelActive() { cancellations.incrementAndGet(); active.get()?.cancel() }
        fun finishActive() { active.get()?.finish() }
        fun parse(result: String): Result? {
            if (result.length > 32_768) return null
            return try {
                val json = JSONObject(result)
                val values = json.optJSONArray("spk") ?: return null
                if (values.length() != OwnerVoicePolicy.DIMENSIONS) return null
                val vector = DoubleArray(values.length()) { values.getDouble(it) }
                val frames = json.optInt("spk_frames")
                val text = json.optString("text").trim()
                if (!OwnerVoicePolicy.valid(vector) || frames < 0 || text.length > 8_192) null else Result(text, vector, frames)
            } catch (_: Exception) { null }
        }

        fun verifiedText(context: Context, result: Result?, binding: String = OwnerVoiceStore.binding(context)): String? {
            if (result == null) return null
            val profile = OwnerVoiceStore.load(context, binding)
            return if (profile.enabled && OwnerVoicePolicy.matches(profile.samples, result.vector, result.frames)) {
                result.text.takeIf { it.isNotBlank() }
            } else null
        }
    }
}
