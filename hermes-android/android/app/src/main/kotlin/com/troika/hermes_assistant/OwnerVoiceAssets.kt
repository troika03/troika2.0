package com.troika.hermes_assistant

import android.content.Context
import org.json.JSONObject
import org.vosk.LibVosk
import org.vosk.Model
import org.vosk.SpeakerModel
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID

/** Verified, packaged models; never downloads audio or model files at runtime. */
internal object OwnerVoiceAssets {
    private var model: Model? = null
    private var speaker: SpeakerModel? = null

    @Synchronized fun speechModel(context: Context): Model {
        LibVosk.vosk_set_log_level(-1)
        if (model == null) model = Model(install(context, "model-wake-ru", "vosk-model-small-ru-0.22").absolutePath)
        return model!!
    }

    @Synchronized fun models(context: Context): Pair<Model, SpeakerModel> {
        speechModel(context)
        if (speaker == null) speaker = SpeakerModel(install(context, "model-owner-voice", "vosk-model-spk-0.4").absolutePath)
        return model!! to speaker!!
    }

    private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it) }

    private fun install(context: Context, asset: String, version: String): File {
        val manifest = context.assets.open("$asset/manifest.json").use { it.readBytes() }
        if (manifest.size > 65_536) throw IOException("Invalid voice model manifest")
        val json = JSONObject(String(manifest, Charsets.UTF_8))
        if (json.getString("version") != version) throw IOException("Unsupported voice model")
        val entries = json.getJSONArray("files")
        if (entries.length() !in 1..128) throw IOException("Invalid voice model")
        data class Entry(val path: String, val size: Long, val digest: String)
        val files = (0 until entries.length()).map { index ->
            val entry = entries.getJSONObject(index)
            Entry(entry.getString("path"), entry.getLong("size"), entry.getString("sha256")).also {
                if (!it.path.matches(Regex("[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")) ||
                    it.path.split('/').any { part -> part == "." || part == ".." } ||
                    it.size !in 0..128_000_000 || !it.digest.matches(Regex("[0-9a-f]{64}"))) {
                    throw IOException("Invalid voice model entry")
                }
            }
        }
        if (files.map { it.path }.toSet().size != files.size || files.sumOf { it.size } > 200_000_000) {
            throw IOException("Invalid voice model size")
        }
        // Reuse the exact wake model installation rather than another 91 MB copy.
        val wakeModel = asset == "model-wake-ru"
        val identity = hash(manifest)
        val root = File(context.noBackupFilesDir, if (wakeModel) "wake-models" else "owner-voice-models").apply { mkdirs() }
        val target = File(root, if (wakeModel) "ru-0.22-$identity" else "$version-$identity")
        fun complete(directory: File): Boolean = files.all { entry ->
            val file = File(directory, entry.path)
            file.isFile && file.length() == entry.size && file.inputStream().use { input ->
                val checksum = MessageDigest.getInstance("SHA-256")
                val buffer = ByteArray(32_768)
                while (true) { val count = input.read(buffer); if (count < 0) break; checksum.update(buffer, 0, count) }
                checksum.digest().joinToString("") { "%02x".format(it) } == entry.digest
            }
        }
        if (target.isDirectory && complete(target)) return target
        val staging = File(root, ".install-${UUID.randomUUID()}")
        if (!staging.mkdir()) throw IOException("Voice model storage unavailable")
        try {
            for (entry in files) {
                val output = File(staging, entry.path)
                output.parentFile!!.mkdirs()
                context.assets.open("$asset/${entry.path}").use { input ->
                    output.outputStream().use { destination -> input.copyTo(destination) }
                }
            }
            if (!complete(staging)) throw IOException("Voice model integrity check failed")
            if (wakeModel) File(staging, ".complete").writeText(identity)
            if (target.exists()) {
                val quarantine = File(root, ".invalid-${UUID.randomUUID()}")
                if (target.parentFile?.canonicalFile != root.canonicalFile || !target.renameTo(quarantine)) {
                    throw IOException("Voice model replacement failed")
                }
            }
            if (!staging.renameTo(target)) throw IOException("Voice model installation failed")
            return target
        } finally {
            if (staging.parentFile?.canonicalFile == root.canonicalFile && staging.exists()) staging.deleteRecursively()
        }
    }
}
