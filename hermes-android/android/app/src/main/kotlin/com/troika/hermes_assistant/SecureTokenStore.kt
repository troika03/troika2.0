package com.troika.hermes_assistant

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Stores the long-lived refresh token encrypted by a non-exportable Keystore key. */
object SecureTokenStore {
    private const val KEY_ALIAS = "troika_refresh_token_key_v1"
    private const val PREFS = "troika_secure_tokens"
    private const val CIPHERTEXT = "refresh_ciphertext"
    private const val IV = "refresh_iv"
    private const val BINDING = "refresh_binding"

    private fun key(): SecretKey {
        require(Build.VERSION.SDK_INT >= Build.VERSION_CODES.M)
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            "AndroidKeyStore",
        )
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }

    @Synchronized fun put(context: Context, token: String, binding: String? = null): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M || token.isBlank()) return false
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val encrypted = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString(CIPHERTEXT, Base64.encodeToString(encrypted, Base64.NO_WRAP))
                .putString(IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
                .putString(BINDING, binding?.let(::digest))
                .commit()
        } catch (_: Exception) {
            false
        }
    }

    @Synchronized fun get(context: Context, binding: String? = null): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return null
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val savedBinding = prefs.getString(BINDING, null)
        if (binding != null && savedBinding != null && savedBinding != digest(binding)) return null
        val ciphertext = prefs.getString(CIPHERTEXT, null) ?: return null
        val iv = prefs.getString(IV, null) ?: return null
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE,
                key(),
                GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
            )
            String(
                cipher.doFinal(Base64.decode(ciphertext, Base64.NO_WRAP)),
                Charsets.UTF_8,
            )
        } catch (_: Exception) {
            clear(context)
            null
        }
    }

    @Synchronized fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().commit()
    }

    private fun digest(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}
