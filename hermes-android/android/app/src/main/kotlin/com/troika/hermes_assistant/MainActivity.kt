package com.troika.hermes_assistant

import android.Manifest
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.PowerManager
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.WindowManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.FlutterEngineCache
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.Locale
import java.util.TimeZone

class MainActivity : FlutterActivity() {

    private val FLUTTER_CHANNEL = "com.troika.hermes/background"
    private val REQ_CALENDAR = 7421
    private val REQ_LOCATION = 7422
    private val REQ_LOCATION_BG = 7423
    private val REQ_SCREEN_CAPTURE = 7424
    private var methodChannel: MethodChannel? = null
    private var pendingScreenConsentResult: MethodChannel.Result? = null
    private var pendingLocalSpeechResult: MethodChannel.Result? = null
    private var preferAgentSpeechConversation = false
    private var localSpeechRecognizer: SpeechRecognizer? = null
    private var backgroundWakePausedForSpeech = false

    override fun onCreate(savedInstanceState: Bundle?) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            (getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager)
                ?.requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
            )
        }
        super.onCreate(savedInstanceState)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        OwnProviderSession.attach(flutterEngine)
        DevelopmentCheckBridge(this, flutterEngine)
        DevelopmentBridge(this, flutterEngine)
        FlutterEngineCache.getInstance().put("main_engine", flutterEngine)

        methodChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            FLUTTER_CHANNEL
        )
        methodChannel!!.setMethodCallHandler { call, result ->
            when (call.method) {
                "beginReminderSync" -> { result.success(ReminderScheduler.beginSync(this)) }
                "syncReminders" -> {
                    val ticket = call.argument<Number>("ticket")?.toLong()
                    val snapshot = call.argument<String>("snapshot") ?: "{}"
                    kotlin.concurrent.thread {
                        try {
                            val status = ticket?.let { ReminderScheduler.applySync(this, org.json.JSONObject(snapshot), it) }
                            runOnUiThread { result.success(status) }
                        } catch (error: Exception) {
                            runOnUiThread { result.error("reminder_sync_failed", "Не удалось установить напоминание на телефоне", null) }
                        }
                    }
                }
                "rejectReminderSync" -> {
                    val ticket = call.argument<Number>("ticket")?.toLong()
                    kotlin.concurrent.thread {
                        val rejected = ticket?.let { ReminderScheduler.rejectSync(this, it) } ?: false
                        runOnUiThread { result.success(rejected) }
                    }
                }
                "clearReminders" -> { NativeReminderDelivery.clear(this); result.success(null) }
                "reminderStatus" -> { result.success(ReminderScheduler.status(this)) }
                "requestExactReminderAlarms" -> {
                    if (Build.VERSION.SDK_INT >= 31 && ReminderScheduler.status(this)["exact_alarms"] != true) {
                        startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName")))
                    }
                    result.success(null)
                }
                "startListenerService" -> { startListenerService(); result.success(null) }
                "stopListenerService" -> { stopListenerService(); result.success(null) }
                "triggerDialog" -> { triggerDialog(); result.success(null) }
                "interruptTts" -> { interruptTts(); result.success(null) }
                "refreshPhoneBridge" -> {
                    refreshPhoneBridge()
                    result.success(null)
                }
                "requestBatteryOptimizationDisable" -> {
                    requestBatteryOptimizationDisable()
                    result.success(null)
                }
                "isBatteryOptimizationIgnored" -> {
                    result.success(isBatteryOptimizationIgnored())
                }
                "getBackgroundVoiceStatus" -> {
                    result.success(backgroundVoiceStatus())
                }
                "requestOverlayPermission" -> {
                    requestOverlayPermission()
                    result.success(null)
                }
                "hasOverlayPermission" -> {
                    result.success(hasOverlayPermission())
                }
                "openAccessibilitySettings" -> {
                    openAccessibilitySettings()
                    result.success(null)
                }
                "isAccessibilityEnabled" -> {
                    result.success(HermesAccessibilityService.instance != null)
                }
                "hasAllFilesAccess" -> {
                    result.success(PhoneFiles.hasAllFilesAccess())
                }
                "requestAllFilesAccess" -> {
                    requestAllFilesAccess()
                    result.success(null)
                }
                "previewEdgeVoice" -> {
                    val voice = call.argument<String>("voice") ?: "ru-RU-SvetlanaNeural"
                    val rate = (call.argument<Number>("rate") ?: 1.0).toDouble()
                    val pitch = (call.argument<Number>("pitch") ?: 0).toInt()
                    val volume = (call.argument<Number>("volume") ?: 0).toInt()
                    previewEdgeVoice(voice, rate, pitch, volume)
                    result.success(null)
                }
                "setEdgeVoice" -> {
                    val voice = call.argument<String>("voice") ?: "ru-RU-SvetlanaNeural"
                    val rate = (call.argument<Number>("rate") ?: 1.0).toDouble()
                    val pitch = (call.argument<Number>("pitch") ?: 0).toInt()
                    val volume = (call.argument<Number>("volume") ?: 0).toInt()
                    setEdgeVoice(voice, rate, pitch, volume)
                    result.success(null)
                }
                "hasCalendarPermission" -> {
                    result.success(hasCalendarPermission())
                }
                "requestCalendarPermission" -> {
                    requestCalendarPermission()
                    result.success(null)
                }
                "hasLocationPermission" -> {
                    result.success(hasLocationPermission())
                }
                "requestLocationPermission" -> {
                    requestLocationPermission()
                    result.success(null)
                }
                "hasBackgroundLocation" -> {
                    result.success(hasBackgroundLocation())
                }
                "requestBackgroundLocation" -> {
                    requestBackgroundLocation()
                    result.success(null)
                }
                "getDeviceContext" -> {
                    // JSON с GPS/wifi/bluetooth-fingerprint для X-Hermes-Device-Context
                    // header. Flutter шлёт этот header при каждом chat-запросе, чтобы
                    // Тройка знала где Миша даже когда запрос идёт из текстового чата
                    // (а не только через wake-word Kotlin-путь).
                    result.success(DeviceContext.asHeaderValue(applicationContext))
                }
                "getTimeZoneId" -> {
                    result.success(TimeZone.getDefault().id)
                }
                "saveAccountSession" -> {
                    val email = call.argument<String>("email").orEmpty()
                    val token = call.argument<String>("token").orEmpty()
                    val refresh = call.argument<String>("refreshToken").orEmpty()
                    val expiry = call.argument<Number>("expiresAtMillis")?.toLong() ?: 0
                    val session = call.argument<String>("sessionId").orEmpty()
                    val replace = call.argument<Boolean>("replaceIdentity") ?: false
                    val expected = call.argument<Number>("expectedGeneration")?.toLong()
                    kotlin.concurrent.thread {
                        val saved = runCatching {
                            NativeAccountSession.saveAccount(applicationContext, email, token, refresh,
                                expiry, session, replace, expected)
                        }.getOrDefault(false)
                        runOnUiThread { result.success(saved) }
                    }
                }
                "clearAccountSession" -> {
                    val expected = call.argument<Number>("expectedGeneration")?.toLong()
                    val mode = call.argument<String>("mode") ?: "signout"
                    kotlin.concurrent.thread {
                        val cleared = runCatching { NativeAccountSession.clear(applicationContext, expected, mode) }.getOrDefault(false)
                        runOnUiThread { result.success(cleared) }
                    }
                }
                "setAccountServerUrl", "setAccountApiKey" -> {
                    val server = call.method == "setAccountServerUrl"
                    val value = call.argument<String>("value").orEmpty()
                    kotlin.concurrent.thread {
                        val saved = runCatching {
                            if (server) NativeAccountSession.setServerUrl(applicationContext, value)
                            else NativeAccountSession.setApiKey(applicationContext, value)
                        }.getOrDefault(false)
                        runOnUiThread { result.success(saved) }
                    }
                }
                "storeRefreshToken" -> {
                    val token = call.argument<String>("token").orEmpty()
                    kotlin.concurrent.thread {
                        val stored = runCatching { SecureTokenStore.put(applicationContext, token) }.getOrDefault(false)
                        runOnUiThread { result.success(stored) }
                    }
                }
                "ensureFreshAccountSession" -> {
                    val force = call.argument<Boolean>("force") == true
                    val identity = NativeAccountSession.snapshot(applicationContext)
                    kotlin.concurrent.thread {
                        val fresh = try {
                            identity != null && NativeAccountSession.accessToken(applicationContext, identity, force).isNotBlank()
                        } catch (_: Exception) { false }
                        runOnUiThread { result.success(fresh) }
                    }
                }
                "getRefreshToken" -> {
                    kotlin.concurrent.thread {
                        val token = SecureTokenStore.get(applicationContext)
                        runOnUiThread { result.success(token) }
                    }
                }
                "clearRefreshToken" -> {
                    kotlin.concurrent.thread {
                        SecureTokenStore.clear(applicationContext)
                        NativeReminderDelivery.clear(applicationContext)
                        runOnUiThread { result.success(null) }
                    }
                }
                "executeLocalCommand" -> {
                    val raw = call.argument<String>("text")?.trim().orEmpty()
                    val response = if (raw.isEmpty()) null else
                        PhoneCommands.tryExecute(
                            applicationContext,
                            raw.lowercase(Locale.forLanguageTag("ru-RU")),
                            raw,
                            preferAgentConversation = call.argument<Boolean>("preferAgentConversation") == true,
                        )
                    result.success(
                        mapOf(
                            "handled" to (response != null),
                            "response" to (response ?: ""),
                            "heard" to raw,
                        )
                    )
                }
                "recognizeLocalCommand" -> {
                    startLocalSpeechRecognition(
                        result,
                        preferAgentConversation = call.argument<Boolean>("preferAgentConversation") == true,
                    )
                }
                "stopLocalSpeechRecognition" -> {
                    stopLocalSpeechRecognition()
                    result.success(null)
                }
                "requestScreenSnapshotConsent" -> {
                    if (ScreenCaptureService.isReady()) {
                        result.success(true)
                    } else if (pendingScreenConsentResult != null) {
                        result.error("consent_pending", "Screen consent is already open", null)
                    } else {
                        pendingScreenConsentResult = result
                        if (!requestScreenSnapshotConsent()) {
                            pendingScreenConsentResult?.success(false)
                            pendingScreenConsentResult = null
                        }
                    }
                }
                "isScreenSnapshotReady" -> {
                    result.success(ScreenCaptureService.isReady())
                }
                "stopScreenSnapshot" -> {
                    stopService(ScreenCaptureService.stopIntent(this))
                    result.success(null)
                }
                "shareFile" -> {
                    val path = call.argument<String>("path") ?: ""
                    result.success(sharePrivateFile(path))
                }
                "getEdgeVoice" -> {
                    val prefs = getSharedPreferences(
                        HermesListenerService.PREFS, MODE_PRIVATE
                    )
                    val data = mapOf(
                        "voice" to prefs.getString("flutter.hermes_edge_voice", "ru-RU-SvetlanaNeural"),
                        "rate" to (prefs.all["flutter.hermes_voice_rate"] as? Double ?: 1.0),
                        "pitch" to (prefs.all["flutter.hermes_voice_pitch"] as? Int ?: 0),
                        "volume" to (prefs.all["flutter.hermes_voice_volume"] as? Int ?: 0),
                    )
                    result.success(data)
                }
                else -> result.notImplemented()
            }
        }

        if (intent?.getBooleanExtra("wake_word_detected", false) == true) {
            methodChannel!!.invokeMethod("wake_word_detected", null)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getBooleanExtra("wake_word_detected", false)) {
            methodChannel?.invokeMethod("wake_word_detected", null)
        }
    }

    override fun onDestroy() {
        try { localSpeechRecognizer?.cancel() } catch (_: Exception) {}
        try { localSpeechRecognizer?.destroy() } catch (_: Exception) {}
        localSpeechRecognizer = null
        pendingLocalSpeechResult = null
        resumeBackgroundWakeAfterSpeech()
        super.onDestroy()
    }

    private fun sharePrivateFile(rawPath: String): Boolean {
        return try {
            val target = File(rawPath).canonicalFile
            val allowedRoots = listOf(cacheDir.canonicalFile, filesDir.canonicalFile)
            val allowed = allowedRoots.any { root ->
                target.path == root.path || target.path.startsWith(root.path + File.separator)
            }
            if (!allowed || !target.isFile) return false

            val mimeType = when (target.extension.lowercase()) {
                "pdf" -> "application/pdf"
                "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                "pptx" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                else -> return false
            }
            val uri = FileProvider.getUriForFile(
                this,
                "$packageName.fileprovider",
                target,
            )
            val sendIntent = Intent(Intent.ACTION_SEND).apply {
                type = mimeType
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(sendIntent, "Поделиться файлом"))
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun startListenerService() {
        val intent = Intent(this, HermesListenerService::class.java).apply {
            action = HermesListenerService.ACTION_START
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun triggerDialog() {
        val intent = Intent(this, HermesListenerService::class.java).apply {
            action = HermesListenerService.ACTION_TRIGGER_DIALOG
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun interruptTts() {
        val intent = Intent(this, HermesListenerService::class.java).apply {
            action = HermesListenerService.ACTION_INTERRUPT_TTS
        }
        // startService — НЕ forground; сервис уже работает, нам нужен лишь сигнал.
        try { startService(intent) } catch (_: Exception) {}
    }

    private fun stopListenerService() {
        val intent = Intent(this, HermesListenerService::class.java).apply {
            action = HermesListenerService.ACTION_STOP
        }
        startService(intent)
    }

    private fun refreshPhoneBridge() {
        val intent = Intent(this, HermesListenerService::class.java).apply {
            action = HermesListenerService.ACTION_REFRESH_PHONE_BRIDGE
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun isBatteryOptimizationIgnored(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    private fun hasOverlayPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(this)
        } else true
    }

    private fun requestOverlayPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        if (hasOverlayPermission()) return
        try {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )
            startActivity(intent)
        } catch (_: Exception) {}
    }

    /** Озвучивает короткую фразу указанным Edge-голосом и параметрами — для preview */
    private fun previewEdgeVoice(
        voice: String,
        rate: Double = 1.0,
        pitch: Int = 0,
        volume: Int = 0,
    ) {
        val prefs = getSharedPreferences(HermesListenerService.PREFS, MODE_PRIVATE)
        val url = HermesListenerService.resolvedUrl(prefs)
        val identity = NativeAccountSession.snapshot(this, url) ?: return
        val key = HermesListenerService.resolvedKey(prefs)
        val sample = if (voice.startsWith("ru-")) {
            "Слушаю. Сейчас восемь часов вечера, дождь до полуночи."
        } else {
            "At your service. The time is eight in the evening."
        }
        Thread {
            try {
                val player = EdgeTtsPlayer(applicationContext, url, key, voice, rate, pitch, volume, identity)
                player.speak(sample) { player.stop() }
            } catch (e: Exception) {
                android.util.Log.e("MainActivity", "preview failed: ${e.message}")
            }
        }.start()
    }

    /** Сохраняет голос + параметры. Перезапускает сервис чтобы изменения вступили в силу. */
    private fun setEdgeVoice(voice: String, rate: Double = 1.0, pitch: Int = 0, volume: Int = 0) {
        val prefs = getSharedPreferences(HermesListenerService.PREFS, MODE_PRIVATE)
        prefs.edit()
            .putString("flutter.hermes_edge_voice", voice)
            .apply()
        // SharedPreferences Edit не поддерживает Double — пишем как Float через putFloat
        // и читаем как Number. Но Flutter shared_preferences хранит как Double напрямую.
        // Используем reflection-friendly approach — write via SharedPreferences.Editor.commit()
        // c приведением к нужным типам.
        val editor = prefs.edit()
        editor.putString("flutter.hermes_edge_voice", voice)
        // Trick: пишем через putFloat — Flutter всё равно читает как num
        editor.putFloat("flutter.hermes_voice_rate", rate.toFloat())
        editor.putInt("flutter.hermes_voice_pitch", pitch)
        editor.putInt("flutter.hermes_voice_volume", volume)
        editor.apply()

        try {
            val stop = Intent(this, HermesListenerService::class.java).apply {
                action = HermesListenerService.ACTION_STOP
            }
            startService(stop)
            Thread.sleep(300)
            val start = Intent(this, HermesListenerService::class.java).apply {
                action = HermesListenerService.ACTION_START
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(start)
            else startService(start)
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "setEdgeVoice restart failed: ${e.message}")
        }
    }

    private fun openAccessibilitySettings() {
        try {
            startActivity(
                Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            )
        } catch (_: Exception) {}
    }

    private fun requestAllFilesAccess() {
        if (PhoneFiles.hasAllFilesAccess()) return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        try {
            startActivity(
                Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
                    data = Uri.parse("package:$packageName")
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            )
        } catch (_: Exception) {
            try {
                startActivity(
                    Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                )
            } catch (_: Exception) {}
        }
    }

    private fun hasCalendarPermission(): Boolean {
        val read = ContextCompat.checkSelfPermission(this, Manifest.permission.READ_CALENDAR) ==
            PackageManager.PERMISSION_GRANTED
        val write = ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_CALENDAR) ==
            PackageManager.PERMISSION_GRANTED
        return read && write
    }

    private fun requestCalendarPermission() {
        if (hasCalendarPermission()) return
        try {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR),
                REQ_CALENDAR
            )
        } catch (_: Exception) {}
    }

    private fun hasLocationPermission(): Boolean {
        val fine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        val coarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    private fun requestLocationPermission() {
        if (hasLocationPermission()) return
        try {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                ),
                REQ_LOCATION
            )
        } catch (_: Exception) {}
    }

    private fun hasBackgroundLocation(): Boolean {
        // До Android 10 фонового разрешения нет — фон работает с обычным.
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return hasLocationPermission()
        return ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_BACKGROUND_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestBackgroundLocation() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        if (hasBackgroundLocation()) return
        // Сначала нужно обычное разрешение; без него фоновое запрашивать нельзя.
        if (!hasLocationPermission()) {
            requestLocationPermission()
            return
        }
        // Android 11+: фоновое нельзя выдать диалогом — только «Разрешать всегда»
        // в системных настройках приложения. Уводим туда.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                intent.data = Uri.parse("package:$packageName")
                startActivity(intent)
            } catch (_: Exception) {}
        } else {
            // Android 10: можно запросить диалогом.
            try {
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION),
                    REQ_LOCATION_BG
                )
            } catch (_: Exception) {}
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            REQ_CALENDAR ->
                methodChannel?.invokeMethod("calendar_permission_result", hasCalendarPermission())
            REQ_LOCATION ->
                methodChannel?.invokeMethod("location_permission_result", hasLocationPermission())
            REQ_LOCATION_BG ->
                methodChannel?.invokeMethod("background_location_result", hasBackgroundLocation())
        }
    }

    private fun backgroundVoiceStatus(): String {
        val prefs = getSharedPreferences(
            HermesListenerService.PREFS, Context.MODE_PRIVATE
        )
        if (!prefs.getBoolean(HermesListenerService.PREF_WAKE_WORD_ENABLED, false)) {
            return "off"
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return "permission_required"
        }
        if (!isBatteryOptimizationIgnored()) return "system_disabled"
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            !SpeechRecognizer.isOnDeviceRecognitionAvailable(this)
        ) return "unavailable"
        return if (HermesListenerService.serviceActive) "working" else "system_disabled"
    }

    @Suppress("DEPRECATION")
    private fun requestScreenSnapshotConsent(): Boolean {
        if (ScreenCaptureService.isReady()) return true
        val manager = getSystemService(MediaProjectionManager::class.java) ?: return false
        startActivityForResult(manager.createScreenCaptureIntent(), REQ_SCREEN_CAPTURE)
        return true
    }

    @Deprecated("Uses the platform MediaProjection consent result")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_SCREEN_CAPTURE) {
            if (resultCode == RESULT_OK && data != null) {
                val serviceIntent = ScreenCaptureService.startIntent(this, resultCode, data)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    startForegroundService(serviceIntent)
                } else {
                    startService(serviceIntent)
                }
                pendingScreenConsentResult?.success(true)
            } else {
                pendingScreenConsentResult?.success(false)
            }
            pendingScreenConsentResult = null
        }
    }

    private fun startLocalSpeechRecognition(
        result: MethodChannel.Result,
        preferAgentConversation: Boolean,
    ) {
        if (pendingLocalSpeechResult != null) {
            result.error("speech_pending", "Распознавание уже запущено", null)
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            result.error("microphone_denied", "Нет доступа к микрофону", null)
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            result.error(
                "speech_unavailable",
                "На устройстве нет системного распознавания речи",
                null,
            )
            return
        }

        val recognizer = try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
                SpeechRecognizer.isOnDeviceRecognitionAvailable(this)
            ) {
                SpeechRecognizer.createOnDeviceSpeechRecognizer(this)
            } else {
                SpeechRecognizer.createSpeechRecognizer(this)
            }
        } catch (e: Exception) {
            result.error(
                "speech_unavailable",
                e.message ?: "Не удалось запустить системное распознавание",
                null,
            )
            return
        }

        pendingLocalSpeechResult = result
        preferAgentSpeechConversation = preferAgentConversation
        localSpeechRecognizer = recognizer
        recognizer.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = Unit
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit

            override fun onPartialResults(partialResults: Bundle?) {
                val partial = partialResults
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    ?.trim()
                    .orEmpty()
                if (partial.isNotEmpty()) {
                    methodChannel?.invokeMethod("debug_heard", partial)
                }
            }

            override fun onResults(results: Bundle?) {
                val heard = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    ?.trim()
                    .orEmpty()
                finishLocalSpeechRecognition(heard)
            }

            override fun onError(error: Int) {
                android.util.Log.i("MainActivity", "System speech ended with code=$error")
                finishLocalSpeechRecognition("")
            }
        })

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
            )
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "ru-RU")
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        }
        pauseBackgroundWakeForSpeech()
        val startDelayMs = if (backgroundWakePausedForSpeech) 300L else 0L
        Handler(mainLooper).postDelayed({
            if (pendingLocalSpeechResult !== result) return@postDelayed
            try {
                recognizer.startListening(intent)
            } catch (e: Exception) {
                pendingLocalSpeechResult = null
                clearLocalSpeechRecognizer()
                result.error(
                    "speech_failed",
                    e.message ?: "Не удалось запустить распознавание",
                    null,
                )
            }
        }, startDelayMs)
    }

    private fun finishLocalSpeechRecognition(heard: String) {
        val pending = pendingLocalSpeechResult ?: return
        pendingLocalSpeechResult = null
        clearLocalSpeechRecognizer()
        val response = if (heard.isEmpty()) null else
            PhoneCommands.tryExecute(
                applicationContext,
                heard.lowercase(Locale.forLanguageTag("ru-RU")),
                heard,
                preferAgentConversation = preferAgentSpeechConversation,
            )
        pending.success(
            mapOf(
                "handled" to (response != null),
                "response" to (response ?: ""),
                "heard" to heard,
            )
        )
    }

    private fun stopLocalSpeechRecognition() {
        try { localSpeechRecognizer?.stopListening() } catch (_: Exception) {}
    }

    private fun clearLocalSpeechRecognizer() {
        try { localSpeechRecognizer?.destroy() } catch (_: Exception) {}
        localSpeechRecognizer = null
        resumeBackgroundWakeAfterSpeech()
    }

    private fun pauseBackgroundWakeForSpeech() {
        if (!HermesListenerService.serviceActive) return
        backgroundWakePausedForSpeech = true
        startService(Intent(this, HermesListenerService::class.java).apply {
            action = HermesListenerService.ACTION_PAUSE_WAKE_FOR_FOREGROUND_SPEECH
        })
    }

    private fun resumeBackgroundWakeAfterSpeech() {
        if (!backgroundWakePausedForSpeech) return
        backgroundWakePausedForSpeech = false
        startService(Intent(this, HermesListenerService::class.java).apply {
            action = HermesListenerService.ACTION_RESUME_WAKE_AFTER_FOREGROUND_SPEECH
        })
    }

    @Suppress("BatteryLife")
    private fun requestBatteryOptimizationDisable() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        if (isBatteryOptimizationIgnored()) return
        try {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.data = Uri.parse("package:$packageName")
            startActivity(intent)
        } catch (e: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (_: Exception) {}
        }
    }
}
