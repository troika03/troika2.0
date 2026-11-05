package com.troika.hermes_assistant

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import org.json.JSONObject
import org.vosk.Recognizer
import java.io.IOException
import java.util.concurrent.Executors

/**
 * Continuous, entirely local wake detection. The system SpeechRecognizer is never
 * created here. Audio is consumed in memory and is neither saved nor transmitted.
 *
 * One serial worker owns the recognizer and recorder. Models are shared with
 * local voice capture for the lifetime of the process. Every callback runs
 * on the main thread. stop's completion is a microphone handoff barrier: callers
 * must wait for it before starting another recorder. close is asynchronous.
 */
internal class OfflineWakeDetector(context: Context) : AutoCloseable {
    enum class Failure { PERMISSION, UNAVAILABLE, AUDIO, TRANSIENT }

    private val context = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { task ->
        Thread(task, "TroikaOfflineWake")
    }
    private val submissions = Any()
    private val audioLock = Any()
    private val state = OfflineWakeState()
    private var closed = false
    // Recorder can be stopped by the caller to unblock a blocking read; release
    // and all native recognizer operations belong to the worker.
    private var recorder: AudioRecord? = null
    private var recorderTicket: OfflineWakeState.Ticket? = null

    fun start(
        onWake: (String?, Long) -> Unit,
        onError: (Failure) -> Unit,
        onReady: () -> Unit = {},
    ): Boolean = synchronized(submissions) {
        if (closed) return false
        val ticket = state.start() ?: return false
        worker.execute { listen(ticket, onWake, onError, onReady) }
        true
    }

    /** Invalidates events now; completion runs after recording has been released. */
    fun stop(onStopped: (() -> Unit)? = null) {
        synchronized(submissions) {
            val ticket = state.stop()
            stopAudio(ticket)
            if (!closed) {
                worker.execute { onStopped?.let { main.post(it) } }
            } else {
                // close queued model cleanup after every existing session. Its
                // completion is posted by that cleanup, even after shutdown.
                onStopped?.let { closeCompletions.add(it) }
                if (closeFinished) drainCloseCompletions()
            }
        }
    }

    private val closeCompletions = mutableListOf<() -> Unit>()
    private var closeFinished = false

    override fun close() {
        synchronized(submissions) {
            if (closed) return
            closed = true
            stopAudio(state.close())
            worker.execute {
                synchronized(submissions) {
                    closeFinished = true
                    drainCloseCompletions()
                }
            }
            worker.shutdown()
        }
    }

    private fun drainCloseCompletions() {
        val callbacks = closeCompletions.toList()
        closeCompletions.clear()
        callbacks.forEach { main.post(it) }
    }

    private fun stopAudio(ticket: OfflineWakeState.Ticket?) {
        if (ticket == null) return
        synchronized(audioLock) {
            if (recorderTicket === ticket) {
                try { recorder?.stop() } catch (_: IllegalStateException) {}
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun listen(
        ticket: OfflineWakeState.Ticket,
        onWake: (String?, Long) -> Unit,
        onError: (Failure) -> Unit,
        onReady: () -> Unit,
    ) {
        var localRecorder: AudioRecord? = null
        var recognizer: Recognizer? = null
        val samples = ShortArray(SAMPLES_PER_READ)
        var matched = false
        var initialQuestion: String? = null
        var profileRevision = OwnerVoiceStore.revision
        var failure: Failure? = null
        var phase = Failure.UNAVAILABLE
        try {
            if (!state.isCurrent(ticket)) return
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) !=
                PackageManager.PERMISSION_GRANTED
            ) throw SecurityException("Microphone permission is required")

            val profile = OwnerVoiceStore.load(context)
            profileRevision = OwnerVoiceStore.revision
            if (!state.isCurrent(ticket)) return
            recognizer = if (profile.enabled) {
                val (voiceModel, speakerModel) = OwnerVoiceAssets.models(context)
                Recognizer(voiceModel, SAMPLE_RATE.toFloat()).also { it.setSpeakerModel(speakerModel) }
            } else Recognizer(OwnerVoiceAssets.speechModel(context), SAMPLE_RATE.toFloat(), GRAMMAR)
            if (!state.isCurrent(ticket)) return
            phase = Failure.AUDIO
            val minimum = AudioRecord.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
            )
            if (minimum <= 0) throw IOException("Unsupported microphone format")
            localRecorder = AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minimum, SAMPLES_PER_READ * 2 * 2),
            )
            if (localRecorder.state != AudioRecord.STATE_INITIALIZED) {
                throw IOException("Microphone could not be initialized")
            }
            synchronized(audioLock) {
                if (!state.isCurrent(ticket)) return
                recorder = localRecorder
                recorderTicket = ticket
                localRecorder.startRecording()
                if (localRecorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                    throw IOException("Microphone could not start recording")
                }
            }
            main.post { if (state.isCurrent(ticket)) onReady() }
            val matcher = OfflineWakeMatcher()
            var emptyReads = 0
            while (state.isCurrent(ticket) && profileRevision == OwnerVoiceStore.revision) {
                val count = localRecorder.read(samples, 0, samples.size)
                if (!state.isCurrent(ticket)) break
                if (count < 0) throw IOException("Microphone read failed")
                if (count == 0) {
                    if (++emptyReads >= 50) throw IOException("Microphone returned no samples")
                    Thread.sleep(10)
                    continue
                }
                emptyReads = 0
                val final = recognizer.acceptWaveForm(samples, count)
                val result = if (final) recognizer.result else recognizer.partialResult
                val text = if (result.length <= 4096) {
                    try { JSONObject(result).optString(if (final) "text" else "partial", "") }
                    catch (_: Exception) { "" }
                } else ""
                samples.fill(0)
                if (matcher.accept(text, final)) {
                    if (!profile.enabled) {
                        matched = true
                        break
                    }
                    // A partial keyword is insufficient to identify a speaker.
                    // Wait for a full sentence; reject before greeting or any action.
                    if (final) {
                        val captured = OwnerVoiceCapture.parse(result)
                        if (captured != null && OwnerVoicePolicy.matches(profile.samples, captured.vector, captured.frames) &&
                            profileRevision == OwnerVoiceStore.revision) {
                            initialQuestion = captured.text.replaceFirst(Regex("(?i)^\\s*тройка[\\s,.:!?-]*"), "").trim()
                            matched = true
                            break
                        }
                    }
                }
                // Reset only the decoder at utterance boundaries. The same
                // AudioRecord remains active through silence and unrelated speech.
                if (final) recognizer.reset()
            }
        } catch (_: SecurityException) {
            failure = Failure.PERMISSION
        } catch (_: LinkageError) {
            failure = Failure.UNAVAILABLE
        } catch (_: OutOfMemoryError) {
            failure = Failure.UNAVAILABLE
        } catch (_: Exception) {
            failure = phase
        } finally {
            synchronized(audioLock) {
                try { localRecorder?.stop() } catch (_: Exception) {}
                try { localRecorder?.release() } catch (_: Exception) {}
                if (recorderTicket === ticket) {
                    recorder = null
                    recorderTicket = null
                }
            }
            try { recognizer?.close() } catch (_: Exception) {}
            samples.fill(0)
        }
        // Microphone ownership has ended before waking the dialog or reporting an
        // error. A paused, replaced, or destroyed session cannot deliver an event.
        if (matched) main.post {
            if (state.finish(ticket) && profileRevision == OwnerVoiceStore.revision) onWake(initialQuestion, profileRevision)
        }
        else failure?.let { reason -> main.post { if (state.finish(ticket)) onError(reason) } }
    }

    companion object {
        private const val SAMPLE_RATE = 16_000
        private const val SAMPLES_PER_READ = 3_200
        // [unk] prevents forcing every unrelated sound into the only known word.
        private const val GRAMMAR = "[\"тройка\", \"[unk]\"]"
    }
}
