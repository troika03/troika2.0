package com.troika.hermes_assistant

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Device-only encrypted embeddings. Audio never reaches this store or backups. */
internal object OwnerVoiceStore {
    data class Profile(val samples: List<DoubleArray> = emptyList(), val enabled: Boolean = false)
    @Volatile var revision: Long = 0
        private set
    private const val ALIAS = "troika_owner_voice_v1"

    fun binding(context: Context): String {
        return binding(NativeAccountSession.eventSnapshot(context))
    }

    fun binding(identity: NativeAccountSession.EventIdentity): String {
        return identity.serverUrl.trimEnd('/') + "\n" + identity.owner.trim().lowercase()
    }

    private fun file(context: Context, binding: String): AtomicFile {
        val digest = MessageDigest.getInstance("SHA-256").digest(binding.toByteArray())
            .joinToString("") { "%02x".format(it) }
        val directory = File(context.noBackupFilesDir, "owner-voice").apply { mkdirs() }
        return AtomicFile(File(directory, "$digest.bin"))
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }

    @Synchronized fun load(context: Context, binding: String = binding(context)): Profile {
        val saved = file(context, binding)
        if (!saved.baseFile.exists()) return Profile()
        try {
            val data = saved.readFully()
            if (data.size !in 29..32_768) throw IllegalStateException("Invalid voice profile")
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, data.copyOfRange(0, 12)))
            cipher.updateAAD(binding.toByteArray(Charsets.UTF_8))
            val plain = cipher.doFinal(data.copyOfRange(12, data.size))
            val json = try { JSONObject(String(plain, Charsets.UTF_8)) } finally { plain.fill(0) }
            if (json.getInt("version") != 1) throw IllegalStateException("Invalid voice profile")
            val values = json.getJSONArray("samples")
            if (values.length() !in 0..OwnerVoicePolicy.REQUIRED_SAMPLES) throw IllegalStateException("Invalid voice profile")
            val samples = (0 until values.length()).map { index ->
                val vector = values.getJSONArray(index)
                if (vector.length() != OwnerVoicePolicy.DIMENSIONS) throw IllegalStateException("Invalid voice vector")
                DoubleArray(vector.length()) { vector.getDouble(it) }.also { require(OwnerVoicePolicy.valid(it)) }
            }
            return Profile(samples, json.optBoolean("enabled") && samples.size == OwnerVoicePolicy.REQUIRED_SAMPLES)
        } catch (_: Exception) {
            // A corrupt existing profile remains protected until explicit deletion.
            return Profile(enabled = true)
        }
    }

    @Synchronized fun save(context: Context, profile: Profile, binding: String = binding(context)) {
        require(profile.samples.size <= OwnerVoicePolicy.REQUIRED_SAMPLES && profile.samples.all(OwnerVoicePolicy::valid))
        require(!profile.enabled || profile.samples.size == OwnerVoicePolicy.REQUIRED_SAMPLES)
        val json = JSONObject().put("version", 1).put("enabled", profile.enabled)
            .put("samples", JSONArray(profile.samples.map { vector -> JSONArray(vector.toList()) }))
        val plain = json.toString().toByteArray(Charsets.UTF_8)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(binding.toByteArray(Charsets.UTF_8))
        val encrypted = try { cipher.doFinal(plain) } finally { plain.fill(0) }
        val saved = file(context, binding)
        var output: java.io.FileOutputStream? = null
        try { output = saved.startWrite(); output.write(cipher.iv); output.write(encrypted); saved.finishWrite(output); revision++ }
        catch (error: Exception) { saved.failWrite(output); throw error }
    }

    @Synchronized fun delete(context: Context, binding: String = binding(context)) { file(context, binding).delete(); revision++ }
    fun enabled(context: Context): Boolean = load(context).enabled
    fun status(context: Context): Map<String, Any> {
        val profile = load(context)
        return mapOf("supported" to true, "enrolled" to (profile.samples.size == OwnerVoicePolicy.REQUIRED_SAMPLES),
            "enabled" to profile.enabled, "samples" to profile.samples.size, "requiredSamples" to OwnerVoicePolicy.REQUIRED_SAMPLES)
    }
}
