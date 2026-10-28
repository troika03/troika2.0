package com.troika.hermes_assistant

import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.BaseDataSource
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Media3 lifecycle stays on one Looper; callbacks and release belong to one lease. */
@UnstableApi
internal class NativeSpeechPlayer(private val context: Context) {
    private val main = Handler(Looper.getMainLooper())
    private val current = AtomicReference<Session?>(null)

    private inner class Session(val audio: NativeStreamingSpeech, val callback: (Boolean) -> Unit) {
        val finished = AtomicBoolean(false)
        var player: ExoPlayer? = null // Main Looper only.
        val timeout = Runnable { finish(false) }
        var playbackObserved = false
        val observePlayback = object : Runnable {
            override fun run() {
                val currentPlayer = player ?: return
                if (finished.get()) return
                if (currentPlayer.isPlaying && currentPlayer.currentPosition > 0) {
                    if (!playbackObserved) { playbackObserved = true; audio.trace("playback_position") }
                } else if (!playbackObserved) main.postDelayed(this, 25)
            }
        }

        fun finish(success: Boolean) {
            synchronized(this) {
                if (!finished.compareAndSet(false, true)) return
            }
            audio.close() // Unblock readers before releasing the loader.
            current.compareAndSet(this, null)
            main.post {
                main.removeCallbacks(timeout)
                main.removeCallbacks(observePlayback)
                try { player?.release() } catch (_: Exception) {} finally { player = null; callback(success) }
            }
        }
    }

    fun play(audio: NativeStreamingSpeech, callback: (Boolean) -> Unit) {
        val session = Session(audio, callback)
        current.getAndSet(session)?.finish(false)
        audio.onPlaybackClose { session.finish(false) }
        main.post {
            if (session.finished.get() || current.get() !== session) return@post
            try {
                val player = ExoPlayer.Builder(context.applicationContext)
                    .setLooper(Looper.getMainLooper())
                    .setLoadControl(DefaultLoadControl.Builder()
                        .setBufferDurationsMs(500, 2000, 150, 250)
                        .setPrioritizeTimeOverSizeThresholds(true).build())
                    .build()
                session.player = player
                // Media3 automatic focus supports MEDIA/GAME only. Keep the
                // existing assistant usage without its incompatible focus mode.
                player.setAudioAttributes(AudioAttributes.Builder()
                    .setUsage(C.USAGE_ASSISTANT).setContentType(C.AUDIO_CONTENT_TYPE_SPEECH).build(), false)
                player.addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(state: Int) {
                        if (state == Player.STATE_ENDED) session.finish(player.currentPosition > 0)
                    }
                    override fun onIsPlayingChanged(isPlaying: Boolean) {
                        if (isPlaying && !session.playbackObserved) main.post(session.observePlayback)
                    }
                    override fun onPlayerError(error: PlaybackException) { session.finish(false) }
                })
                val factory = DataSource.Factory { MemorySource(audio.buffer) }
                val source = ProgressiveMediaSource.Factory(factory)
                    .setLoadErrorHandlingPolicy(DefaultLoadErrorHandlingPolicy(0))
                    .createMediaSource(MediaItem.Builder().setUri("troika-memory://speech")
                        .setMimeType(MimeTypes.AUDIO_MPEG).build())
                player.setMediaSource(source)
                player.volume = 1f
                player.setPlaybackSpeed(1.10f)
                synchronized(session) {
                    if (!session.finished.get()) {
                        player.prepare()
                        player.play()
                        main.postDelayed(session.timeout, 90_000)
                    }
                }
            } catch (_: Exception) { session.finish(false) }
        }
    }

    fun stop() { current.getAndSet(null)?.finish(false) }

    private class MemorySource(private val buffer: SpeechAudioBuffer) : BaseDataSource(false) {
        private var spec: DataSpec? = null
        private var position = 0L
        private var remaining = C.LENGTH_UNSET.toLong()
        @Volatile private var closed = true

        override fun open(dataSpec: DataSpec): Long {
            transferInitializing(dataSpec)
            spec = dataSpec
            position = dataSpec.position
            remaining = dataSpec.length
            closed = false
            transferStarted(dataSpec)
            return remaining // Unknown size lets extraction begin before EOF.
        }

        override fun read(target: ByteArray, offset: Int, length: Int): Int {
            if (length == 0) return 0
            if (remaining == 0L) return C.RESULT_END_OF_INPUT
            val count = buffer.readAt(position, target, offset,
                if (remaining == C.LENGTH_UNSET.toLong()) length else minOf(length.toLong(), remaining).toInt()) { closed }
            if (count < 0) return C.RESULT_END_OF_INPUT
            position += count
            if (remaining != C.LENGTH_UNSET.toLong()) remaining -= count
            bytesTransferred(count)
            return count
        }

        override fun getUri(): Uri? = spec?.uri

        override fun close() {
            if (closed) return
            closed = true
            spec = null
            buffer.wakeReaders()
            transferEnded()
            // Media3 may reopen this source; only its owner clears RAM/HTTP.
        }
    }
}
