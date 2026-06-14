package com.troika.hermes_assistant

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.util.Log
import kotlin.concurrent.thread
import kotlin.math.PI
import kotlin.math.sin

/**
 * Короткие звуковые сигналы обратной связи для голосового UX.
 *
 * Все семплы синтезируются на лету (синусоида + envelope), без внешних файлов.
 * Воспроизведение неблокирующее.
 */
object SoundFeedback {
    private const val TAG = "SoundFb"
    private const val SAMPLE_RATE = 44100

    fun heard() = playBeep(880.0, 70, 0.25)
    fun thinking() = playBeep(660.0, 50, 0.18)
    fun ready() = playBeep(990.0, 60, 0.22)
    fun dismiss() = playBeep(440.0, 80, 0.2)

    private fun playBeep(freqHz: Double, durMs: Int, volume: Double) {
        thread(name = "SoundFb", isDaemon = true) {
            try {
                val samples = SAMPLE_RATE * durMs / 1000
                val pcm = ShortArray(samples)
                val fadeIn = (samples * 0.15).toInt().coerceAtLeast(1)
                val fadeOut = (samples * 0.6).toInt().coerceAtLeast(1)
                val fadeOutStart = samples - fadeOut
                for (i in 0 until samples) {
                    val env = when {
                        i < fadeIn -> i.toDouble() / fadeIn
                        i >= fadeOutStart -> (samples - i).toDouble() / fadeOut
                        else -> 1.0
                    }
                    val v = sin(2.0 * PI * freqHz * i / SAMPLE_RATE) * env * volume
                    pcm[i] = (v * Short.MAX_VALUE).toInt().toShort()
                }

                val track = AudioTrack.Builder()
                    .setAudioAttributes(
                        AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                            .build()
                    )
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(SAMPLE_RATE)
                            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                            .build()
                    )
                    .setBufferSizeInBytes(pcm.size * 2)
                    .setTransferMode(AudioTrack.MODE_STATIC)
                    .build()

                track.write(pcm, 0, pcm.size)
                track.play()
                Thread.sleep(durMs.toLong() + 80)
                track.release()
            } catch (e: Exception) {
                Log.w(TAG, "beep failed: ${e.message}")
            }
        }
    }
}
