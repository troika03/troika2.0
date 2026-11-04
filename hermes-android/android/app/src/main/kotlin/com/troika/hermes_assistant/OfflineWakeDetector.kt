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
import org.vosk.LibVosk
import org.vosk.Model
import org.vosk.Recognizer
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Continuous, entirely local wake detection. The system SpeechRecognizer is never
 * created here. Audio is consumed in memory and is neither saved nor transmitted.
 *
 * One serial worker owns the model, recognizer, and recorder. Every callback runs
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
    // Model is accessed only by the serial worker.
    private var model: Model? = null
    // Recorder can be stopped by the caller to unblock a blocking read; release
    // and all native recognizer operations belong to the worker.
    private var recorder: AudioRecord? = null
    private var recorderTicket: OfflineWakeState.Ticket? = null

    fun start(
        onWake: () -> Unit,
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
                try { model?.close() } catch (_: Exception) {}
                model = null
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
        onWake: () -> Unit,
        onError: (Failure) -> Unit,
        onReady: () -> Unit,
    ) {
        var localRecorder: AudioRecord? = null
        var recognizer: Recognizer? = null
        val samples = ShortArray(SAMPLES_PER_READ)
        var matched = false
        var failure: Failure? = null
        var phase = Failure.UNAVAILABLE
        try {
            if (!state.isCurrent(ticket)) return
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) !=
                PackageManager.PERMISSION_GRANTED
            ) throw SecurityException("Microphone permission is required")

            if (model == null) {
                val directory = prepareModel(ticket)
                if (!state.isCurrent(ticket)) return
                // Native diagnostics must not include recognition content.
                LibVosk.vosk_set_log_level(-1)
                model = Model(directory.absolutePath)
            }
            if (!state.isCurrent(ticket)) return
            recognizer = Recognizer(model!!, SAMPLE_RATE.toFloat(), GRAMMAR)
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
            while (state.isCurrent(ticket)) {
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
                    matched = true
                    break
                }
                // Reset only the decoder at utterance boundaries. The same
                // AudioRecord remains active through silence and unrelated speech.
                if (final) recognizer.reset()
            }
        } catch (_: Cancelled) {
            // Stop during asset preparation is normal and has no error callback.
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
        if (matched) main.post { if (state.finish(ticket)) onWake() }
        else failure?.let { reason -> main.post { if (state.finish(ticket)) onError(reason) } }
    }

    private class Cancelled : Exception()
    private data class ModelFile(val path: String, val size: Long, val sha256: String)

    private fun prepareModel(ticket: OfflineWakeState.Ticket): File {
        val manifest = context.assets.open("$ASSET_DIRECTORY/manifest.json").use { input ->
            val bytes = input.readBytes()
            if (bytes.size > 65_536) throw IOException("Invalid wake model manifest")
            bytes
        }
        val identity = digest(manifest)
        val json = JSONObject(String(manifest, Charsets.UTF_8))
        if (json.getString("version") != "vosk-model-small-ru-0.22") {
            throw IOException("Unsupported wake model version")
        }
        val entries = json.getJSONArray("files")
        if (entries.length() !in 1..128) throw IOException("Invalid wake model file count")
        val files = (0 until entries.length()).map { index ->
            val entry = entries.getJSONObject(index)
            val path = entry.getString("path")
            val size = entry.getLong("size")
            val sha256 = entry.getString("sha256")
            if (!path.matches(Regex("[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")) ||
                path.split('/').any { it == "." || it == ".." } ||
                size !in 0..128_000_000 || !sha256.matches(Regex("[0-9a-f]{64}"))
            ) throw IOException("Invalid wake model file entry")
            ModelFile(path, size, sha256)
        }
        if (files.map { it.path }.toSet().size != files.size ||
            files.sumOf { it.size } > 200_000_000
        ) throw IOException("Invalid wake model size")
        val root = File(context.noBackupFilesDir, "wake-models")
        if (!root.isDirectory && !root.mkdirs()) throw IOException("Wake model storage unavailable")
        val target = File(root, "ru-0.22-$identity")
        fun complete(): Boolean {
            val marker = File(target, COMPLETE_MARKER)
            if (!marker.isFile || marker.length() != identity.length.toLong() ||
                marker.readText() != identity
            ) return false
            val buffer = ByteArray(32_768)
            for (entry in files) {
                if (!state.isCurrent(ticket)) throw Cancelled()
                val file = File(target, entry.path)
                if (!file.isFile || file.length() != entry.size) return false
                val checksum = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    while (true) {
                        if (!state.isCurrent(ticket)) throw Cancelled()
                        val count = input.read(buffer)
                        if (count < 0) break
                        checksum.update(buffer, 0, count)
                    }
                }
                if (hex(checksum.digest()) != entry.sha256) return false
            }
            return true
        }
        if (complete()) return target
        val staging = File(root, ".install-${UUID.randomUUID()}")
        if (!staging.mkdir()) throw IOException("Wake model staging unavailable")
        try {
            val buffer = ByteArray(32_768)
            for (file in files) {
                if (!state.isCurrent(ticket)) throw Cancelled()
                val output = File(staging, file.path)
                if (!output.parentFile!!.isDirectory && !output.parentFile!!.mkdirs()) {
                    throw IOException("Wake model directory unavailable")
                }
                val checksum = MessageDigest.getInstance("SHA-256")
                var copied = 0L
                context.assets.open("$ASSET_DIRECTORY/${file.path}").use { input ->
                    output.outputStream().use { stream ->
                        while (true) {
                            if (!state.isCurrent(ticket)) throw Cancelled()
                            val count = input.read(buffer)
                            if (count < 0) break
                            copied += count
                            if (copied > file.size) throw IOException("Wake model size mismatch")
                            checksum.update(buffer, 0, count)
                            stream.write(buffer, 0, count)
                        }
                    }
                }
                if (copied != file.size || hex(checksum.digest()) != file.sha256) {
                    throw IOException("Wake model integrity check failed")
                }
            }
            File(staging, COMPLETE_MARKER).writeText(identity)
            if (!state.isCurrent(ticket)) throw Cancelled()
            if (target.exists()) {
                if (complete()) return target
                // A failed or corrupt installation must not permanently block a
                // retry. Preserve that exact owned folder for diagnosis; never
                // recursively remove an existing model used by another service.
                val quarantine = File(root, "ru-0.22-$identity.invalid-${UUID.randomUUID()}")
                if (target.parentFile?.canonicalFile != root.canonicalFile ||
                    !target.renameTo(quarantine)
                ) throw IOException("Wake model replacement failed")
            }
            if (!staging.renameTo(target) && !complete()) {
                throw IOException("Wake model installation failed")
            }
            return target
        } finally {
            // Only this invocation's random staging child can be removed.
            if (staging.parentFile?.canonicalFile == root.canonicalFile && staging.exists()) {
                staging.deleteRecursively()
            }
        }
    }

    private fun digest(bytes: ByteArray): String = hex(MessageDigest.getInstance("SHA-256").digest(bytes))
    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

    companion object {
        private const val SAMPLE_RATE = 16_000
        private const val SAMPLES_PER_READ = 3_200
        private const val ASSET_DIRECTORY = "model-wake-ru"
        private const val COMPLETE_MARKER = ".complete"
        // [unk] prevents forcing every unrelated sound into the only known word.
        private const val GRAMMAR = "[\"тройка\", \"[unk]\"]"
    }
}
