package com.troika.hermes_assistant

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat

/** Short-lived natural speech for a delivered, still-current reminder. */
class ReminderVoiceService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val queue = ReminderSpeechQueue()
    private var alive = true
    private var edge: EdgeTtsPlayer? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private val timeout = Runnable { stopSelf() }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Озвучивание напоминаний", NotificationManager.IMPORTANCE_LOW))
        startForeground(FOREGROUND_ID, NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher).setContentTitle("Тройка")
            .setContentText("Озвучивание напоминания").setSilent(true).setOngoing(true).build())
        wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Troika:ReminderSpeech").also { it.acquire(90_000) }
        handler.postDelayed(timeout, 60_000)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val id = intent?.getStringExtra("id").orEmpty()
        val owner = intent?.getStringExtra("owner").orEmpty()
        val reminder = ReminderSpeechQueue.Reminder(owner, id, ReminderScheduler.spokenText(this, owner, id))
        if (!isCurrent(reminder) || !speechAllowed()) {
            Log.i(TAG, "speech_skipped_unavailable")
            if (queue.isEmpty) stopSelf(startId)
            return START_NOT_STICKY
        }
        queue.enqueue(reminder)
        speakNext()
        return START_NOT_STICKY
    }

    private fun speechAllowed(): Boolean {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        return ReminderScheduler.status(this)["notifications_enabled"] == true &&
            manager.currentInterruptionFilter == NotificationManager.INTERRUPTION_FILTER_ALL
    }

    private fun isCurrent(reminder: ReminderSpeechQueue.Reminder): Boolean = reminder.text.isNotBlank() &&
        ReminderScheduler.spokenText(this, reminder.owner, reminder.id) == reminder.text

    private fun reconcile() {
        if (!alive) return
        if (queue.reconcile { isCurrent(it) && speechAllowed() }) {
            edge?.stop()
            edge = null
        }
        speakNext()
    }

    private fun finish(playback: ReminderSpeechQueue.Playback) {
        if (!alive || !queue.finish(playback)) return
        edge = null
        speakNext()
    }

    private fun speakNext() {
        if (!alive || queue.active != null) return
        val playback = queue.next { isCurrent(it) && speechAllowed() }
        if (playback != null) {
            val reminder = playback.reminder
            Thread {
                val prefs = getSharedPreferences(HermesListenerService.PREFS, Context.MODE_PRIVATE)
                val identity = NativeAccountSession.snapshot(this)
                val token = if (identity == null) "" else NativeAccountSession.accessToken(this, identity)
                handler.post {
                    if (!alive || queue.active != playback) return@post
                    if (identity == null || token.isBlank() || !NativeAccountSession.current(this, identity) ||
                        !isCurrent(reminder) || !speechAllowed()) {
                        Log.i(TAG, "neural_speech_unavailable")
                        finish(playback)
                        return@post
                    }
                    val voice = prefs.getString("flutter.hermes_edge_voice", null) ?: "ru-RU-SvetlanaNeural"
                    val rate = (prefs.all["flutter.hermes_voice_rate"] as? Number)?.toDouble() ?: 1.0
                    val pitch = (prefs.all["flutter.hermes_voice_pitch"] as? Number)?.toInt() ?: 0
                    val player = EdgeTtsPlayer(applicationContext, identity.serverUrl, token, voice, rate, pitch,
                        expectedIdentity = identity)
                    edge = player
                    Log.i(TAG, "neural_speech_requested")
                    player.speak(reminder.text, onDone = {
                        handler.post { finish(playback) }
                    }, onUnavailable = {
                        handler.post {
                            Log.i(TAG, "neural_speech_unavailable")
                            finish(playback)
                        }
                    })
                }
            }.apply { name = "ReminderSpeechAuth"; start() }
            return
        }
        Log.i(TAG, "speech_finished")
        stopSelf()
    }

    override fun onDestroy() {
        alive = false
        queue.clear()
        if (instance === this) instance = null
        edge?.stop()
        edge = null
        handler.removeCallbacksAndMessages(null)
        if (wakeLock?.isHeld == true) wakeLock?.release()
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    companion object {
        private const val TAG = "TroikaReminderVoice"
        private const val CHANNEL = "troika_reminder_voice"
        private const val FOREGROUND_ID = 172904
        @Volatile private var instance: ReminderVoiceService? = null

        fun remindersChanged() {
            instance?.let { service -> service.handler.post { service.reconcile() } }
        }
    }
}
