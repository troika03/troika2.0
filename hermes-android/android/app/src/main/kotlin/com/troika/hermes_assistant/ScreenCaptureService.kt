package com.troika.hermes_assistant

import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import android.util.Base64
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.sqrt

/** One-consent, one-frame MediaProjection service. Raw pixels never touch disk. */
class ScreenCaptureService : Service() {
    companion object {
        private const val CHANNEL_ID = "troika_screen_capture"
        private const val NOTIFICATION_ID = 3107
        private const val ACTION_START = "com.troika.hermes_assistant.SCREEN_START"
        private const val ACTION_STOP = "com.troika.hermes_assistant.SCREEN_STOP"
        private const val EXTRA_RESULT_CODE = "result_code"
        private const val EXTRA_RESULT_DATA = "result_data"
        private const val CONSENT_TTL_MS = 120_000L
        private const val HARD_MAX_EDGE = 1280
        private const val HARD_MAX_PIXELS = 1280 * 720
        private const val HARD_MAX_BYTES = 600 * 1024

        @Volatile private var instance: ScreenCaptureService? = null

        fun isReady(): Boolean = instance?.isProjectionReady() == true

        fun capture(params: JSONObject): JSONObject =
            instance?.captureOneFrame(params) ?: error("local_consent_required")

        fun startIntent(context: Context, resultCode: Int, data: Intent): Intent =
            Intent(context, ScreenCaptureService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, data)
            }

        fun stopIntent(context: Context): Intent =
            Intent(context, ScreenCaptureService::class.java).apply { action = ACTION_STOP }

        private fun error(message: String): JSONObject = JSONObject().apply {
            put("ok", false)
            put("error", message)
        }
    }

    private val projectionLock = Any()
    private var projection: MediaProjection? = null
    private var expiresAtElapsed = 0L
    private var captureInProgress = false
    private val expiryHandler = Handler(android.os.Looper.getMainLooper())

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannel()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopProjection()
            ACTION_START -> startProjection(intent)
        }
        return START_NOT_STICKY
    }

    private fun startProjection(intent: Intent) {
        showForegroundNotification()
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val data = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(EXTRA_RESULT_DATA)
        }
        if (resultCode != Activity.RESULT_OK || data == null) {
            stopProjection()
            return
        }
        synchronized(projectionLock) {
            projection?.stop()
            val manager = getSystemService(MediaProjectionManager::class.java)
            projection = manager?.getMediaProjection(resultCode, data)
            projection?.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    synchronized(projectionLock) {
                        projection = null
                        expiresAtElapsed = 0L
                    }
                    removeForegroundNotification()
                    stopSelf()
                }
            }, Handler(mainLooper))
            expiresAtElapsed = SystemClock.elapsedRealtime() + CONSENT_TTL_MS
        }
        expiryHandler.removeCallbacksAndMessages(null)
        expiryHandler.postDelayed({ stopProjection() }, CONSENT_TTL_MS)
    }

    private fun isProjectionReady(): Boolean = synchronized(projectionLock) {
        projection != null && SystemClock.elapsedRealtime() < expiresAtElapsed && !captureInProgress
    }

    private fun captureOneFrame(params: JSONObject): JSONObject {
        val sessionId = params.optString("vision_session_id")
        val nonce = params.optString("session_nonce")
        if (sessionId.isBlank() || nonce.isBlank()) return error("vision_session_required")

        val accessibility = HermesAccessibilityService.instance
            ?: return error("accessibility_required_for_sensitive_screen_guard")
        val activePackage = accessibility.activePackageName()
            ?: return error("active_screen_unavailable")
        if (isSensitivePackage(activePackage)) return error("sensitive_screen_blocked")
        if (accessibility.hasSensitiveContentOnScreen()) return error("sensitive_screen_blocked")

        val currentProjection = synchronized(projectionLock) {
            if (!isProjectionReady()) return error("local_consent_required_or_expired")
            captureInProgress = true
            projection
        } ?: return error("local_consent_required")

        val maxEdge = params.optInt("max_edge", HARD_MAX_EDGE).coerceIn(320, HARD_MAX_EDGE)
        val maxBytes = params.optInt("max_bytes", HARD_MAX_BYTES).coerceIn(64 * 1024, HARD_MAX_BYTES)
        val result = captureBitmap(currentProjection, activePackage, maxEdge, maxBytes)
        synchronized(projectionLock) { captureInProgress = false }
        stopProjection()
        if (!result.optBoolean("ok")) return result
        result.put("vision_session_id", sessionId)
        result.put("session_nonce", nonce)
        return result
    }

    private fun captureBitmap(
        currentProjection: MediaProjection,
        expectedPackage: String,
        maxEdge: Int,
        maxBytes: Int,
    ): JSONObject {
        val metrics = resources.displayMetrics
        val windowManager = getSystemService(WindowManager::class.java)
        val bounds = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            windowManager.currentWindowMetrics.bounds
        } else null
        val width = bounds?.width() ?: metrics.widthPixels
        val height = bounds?.height() ?: metrics.heightPixels
        if (width < 1 || height < 1) return error("invalid_display_size")

        val thread = HandlerThread("TroikaScreenCapture").apply { start() }
        val handler = Handler(thread.looper)
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        val latch = CountDownLatch(1)
        var display: VirtualDisplay? = null
        var output: JSONObject? = null
        reader.setOnImageAvailableListener({ source ->
            val image = source.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val guard = HermesAccessibilityService.instance
                val packageAtCapture = guard?.activePackageName()
                if (
                    guard == null ||
                    packageAtCapture != expectedPackage ||
                    packageAtCapture == null ||
                    isSensitivePackage(packageAtCapture) ||
                    guard.hasSensitiveContentOnScreen()
                ) {
                    output = error("sensitive_or_changed_screen_blocked")
                    return@setOnImageAvailableListener
                }
                val plane = image.planes[0]
                val rowPadding = plane.rowStride - plane.pixelStride * width
                val paddedWidth = width + rowPadding / plane.pixelStride
                val padded = Bitmap.createBitmap(paddedWidth, height, Bitmap.Config.ARGB_8888)
                padded.copyPixelsFromBuffer(plane.buffer)
                val cropped = Bitmap.createBitmap(padded, 0, 0, width, height)
                if (cropped !== padded) padded.recycle()
                val scaled = scaleForLimits(cropped, maxEdge)
                if (scaled !== cropped) cropped.recycle()
                val encoded = encodeJpeg(scaled, maxBytes)
                val finalWidth = scaled.width
                val finalHeight = scaled.height
                scaled.recycle()
                output = if (encoded == null) {
                    error("frame_cannot_fit_size_limit")
                } else {
                    JSONObject().apply {
                        put("ok", true)
                        put("encoding", "base64")
                        put("format", "jpeg")
                        put("size", encoded.size)
                        put("width", finalWidth)
                        put("height", finalHeight)
                        put("image", Base64.encodeToString(encoded, Base64.NO_WRAP))
                    }
                }
            } catch (_: Exception) {
                output = error("screen_capture_failed")
            } finally {
                image.close()
                latch.countDown()
            }
        }, handler)
        try {
            display = currentProjection.createVirtualDisplay(
                "TroikaOneFrame",
                width,
                height,
                metrics.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.surface,
                null,
                handler,
            )
            if (!latch.await(8, TimeUnit.SECONDS)) return error("screen_capture_timeout")
            return output ?: error("screen_capture_empty")
        } catch (_: Exception) {
            return error("screen_capture_failed")
        } finally {
            display?.release()
            reader.close()
            thread.quitSafely()
        }
    }

    private fun scaleForLimits(source: Bitmap, maxEdge: Int): Bitmap {
        val edgeScale = min(1.0, maxEdge.toDouble() / maxOf(source.width, source.height))
        val pixelScale = min(1.0, sqrt(HARD_MAX_PIXELS.toDouble() / (source.width * source.height)))
        val scale = min(edgeScale, pixelScale)
        if (scale >= 0.999) return source
        return Bitmap.createScaledBitmap(
            source,
            (source.width * scale).toInt().coerceAtLeast(1),
            (source.height * scale).toInt().coerceAtLeast(1),
            true,
        )
    }

    private fun encodeJpeg(source: Bitmap, maxBytes: Int): ByteArray? {
        for (quality in listOf(82, 72, 62, 52, 42, 32)) {
            val stream = ByteArrayOutputStream()
            source.compress(Bitmap.CompressFormat.JPEG, quality, stream)
            val bytes = stream.toByteArray()
            if (bytes.size <= maxBytes) return bytes
        }
        return null
    }

    private fun isSensitivePackage(packageName: String): Boolean {
        val value = packageName.lowercase()
        val blockedFragments = listOf(
            "permissioncontroller", "systemui", "com.android.settings",
            "bank", "banking", "sber", "tinkoff", "vtb", "raiffeisen",
            "yoomoney", "qiwi", "paypal", "revolut", "binance", "crypto", "wallet",
            "bitwarden", "1password", "keepass", "lastpass", "authenticator",
        )
        if (blockedFragments.any(value::contains)) return true
        val custom = getSharedPreferences("FlutterSharedPreferences", MODE_PRIVATE)
            .getString("flutter.screen_snapshot_blocked_packages", "")
            .orEmpty()
            .split(',')
            .map { it.trim().lowercase() }
            .filter { it.isNotEmpty() }
        return custom.any { value == it || value.startsWith("$it.") }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Показ экрана Тройке",
                    NotificationManager.IMPORTANCE_LOW,
                )
            )
        }
    }

    private fun showForegroundNotification() {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            1,
            stopIntent(this),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("Тройка может получить один снимок")
            .setContentText("Разрешение истечёт через 2 минуты")
            .setContentIntent(open)
            .addAction(0, "Остановить", stop)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun stopProjection() {
        expiryHandler.removeCallbacksAndMessages(null)
        val current = synchronized(projectionLock) {
            val value = projection
            projection = null
            expiresAtElapsed = 0L
            captureInProgress = false
            value
        }
        try { current?.stop() } catch (_: Exception) {}
        removeForegroundNotification()
        stopSelf()
    }

    private fun removeForegroundNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        stopProjection()
        super.onDestroy()
    }
}
