package com.troika.hermes_assistant

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.Uri
import android.provider.AlarmClock
import android.provider.Settings
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import org.json.JSONObject

/**
 * Исполнитель команд, приходящих от Hermes-LLM через WebSocket.
 * Для простых intents — использует [PhoneCommands] и Android API напрямую.
 * Для tap/type/swipe/read_screen — делегирует [HermesAccessibilityService].
 */
object PhoneCommandExecutor {
    private const val TAG = "PhoneExec"

    fun execute(ctx: Context, action: String, params: JSONObject): JSONObject {
        Log.i(TAG, "Command execution started")
        return when (action) {
            "open_app" -> openApp(ctx, params.optString("app"))
            "call" -> dial(ctx, params.optString("number"))
            "send_sms" -> sendSms(ctx, params.optString("number"), params.optString("text"))
            "set_alarm" -> setAlarm(ctx, params.optInt("hour"), params.optInt("minute", 0), params.optString("label"))
            "set_timer" -> setTimer(ctx, params.optInt("seconds"))
            "navigate" -> navigate(ctx, params.optString("destination"))
            "web_search" -> webSearch(ctx, params.optString("query"))
            "open_url" -> openUrl(ctx, params.optString("url"))
            // Уведомление о готовности фоновой задачи (job_runner)
            "notify_voice" -> notifyUser(
                ctx,
                params.optString("text"),
                true,
                "Тройка",
            )
            "volume" -> setVolume(ctx, params.opt("level"))
            "brightness" -> setBrightness(ctx, params.opt("level"))
            "tap" -> accessibility { it.tapOn(params) }
            "type_text" -> accessibility { it.typeText(params.optString("text")) }
            "swipe" -> accessibility { it.swipe(params.optString("direction")) }
            "press_back" -> accessibility { it.pressBack() }
            "press_home" -> pressHome(ctx)
            "read_screen" -> accessibility { it.readScreen() }
            "status" -> status(ctx)
            // ── Файловые операции ─────────────────────────────────────
            "file_list" -> PhoneFiles.listFiles(
                ctx,
                params.optString("path", ""),
                params.optBoolean("recursive", false),
                if (params.has("pattern") && !params.isNull("pattern")) params.optString("pattern") else null,
            )
            "file_read" -> PhoneFiles.readFile(
                ctx,
                params.optString("path"),
                params.optString("encoding", "auto"),
                params.optInt("max_bytes", 5 * 1024 * 1024),
            )
            "file_write" -> PhoneFiles.writeFile(
                ctx,
                params.optString("path"),
                params.optString("content"),
                params.optString("encoding", "text"),
                params.optBoolean("append", false),
            )
            "file_delete" -> PhoneFiles.deleteFile(
                ctx,
                params.optString("path"),
                params.optBoolean("recursive", false),
            )
            "file_move" -> PhoneFiles.moveFile(
                ctx,
                params.optString("src"),
                params.optString("dst"),
                params.optBoolean("overwrite", false),
            )
            "file_info" -> PhoneFiles.fileInfo(ctx, params.optString("path"))
            "save_to_gallery" -> PhoneFiles.saveToGallery(
                ctx,
                params.optString("filename"),
                params.optString("content"),
            )
            "request_all_files_access" -> requestAllFilesAccess(ctx)
            // ── Системные ──────────────────────────────────────────
            "clipboard_get" -> PhoneSystem.clipboardGet(ctx)
            "clipboard_set" -> PhoneSystem.clipboardSet(ctx, params.optString("text"))
            "torch" -> PhoneSystem.torch(ctx, params.optBoolean("on", true))
            "torch_toggle" -> PhoneSystem.torchToggle(ctx)
            "battery" -> PhoneSystem.battery(ctx)
            "network" -> PhoneSystem.network(ctx)
            "camera_photo" -> PhoneSystem.cameraTakePhoto(ctx, params.optBoolean("front", false))
            "screenshot" -> accessibility { it.takeScreenshot() }
            "screen_snapshot" -> ScreenCaptureService.capture(params)
            // ── Календарь ───────────────────────────────────────────
            "calendar_list_calendars" -> PhoneCalendar.listCalendars(ctx)
            "calendar_list_events" -> PhoneCalendar.listEvents(
                ctx,
                if (params.has("from") && !params.isNull("from")) params.optString("from") else null,
                if (params.has("to") && !params.isNull("to")) params.optString("to") else null,
                params.optInt("max", 50),
            )
            "calendar_create_event" -> PhoneCalendar.createEvent(
                ctx,
                params.optString("title"),
                params.optString("start"),
                if (params.has("end") && !params.isNull("end")) params.optString("end") else null,
                if (params.has("description") && !params.isNull("description")) params.optString("description") else null,
                if (params.has("location") && !params.isNull("location")) params.optString("location") else null,
                if (params.has("reminder_minutes") && !params.isNull("reminder_minutes")) params.optInt("reminder_minutes") else null,
                if (params.has("calendar_id") && !params.isNull("calendar_id")) params.optLong("calendar_id") else null,
            )
            "calendar_update_event" -> PhoneCalendar.updateEvent(
                ctx,
                params.optLong("event_id"),
                if (params.has("title") && !params.isNull("title")) params.optString("title") else null,
                if (params.has("start") && !params.isNull("start")) params.optString("start") else null,
                if (params.has("end") && !params.isNull("end")) params.optString("end") else null,
                if (params.has("description") && !params.isNull("description")) params.optString("description") else null,
                if (params.has("location") && !params.isNull("location")) params.optString("location") else null,
            )
            "calendar_delete_event" -> PhoneCalendar.deleteEvent(ctx, params.optLong("event_id"))
            "calendar_check_permissions" -> PhoneCalendar.requestPermissions(ctx)
            // ── Server-initiated push (Тройка сама заговаривает) ──────
            "notify_user" -> notifyUser(
                ctx,
                params.optString("text"),
                params.optBoolean("speak", true),
                if (params.has("title") && !params.isNull("title")) params.optString("title") else "Тройка",
            )
            else -> err("unknown_action")
        }
    }

    // ---- Простые intents -------------------------------------------------

    private fun openApp(ctx: Context, name: String): JSONObject {
        if (name.isBlank()) return err("missing app")
        // Сначала проверяем алиасы из PhoneCommands.APP_ALIASES (через прямой матч имени)
        val pkg = findPackage(ctx, name)
        if (pkg == null) return err("app_not_found")
        val intent = ctx.packageManager.getLaunchIntentForPackage(pkg)
        return if (intent != null) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
            ok(mapOf("package" to pkg, "message" to "app opened"))
        } else {
            err("no_launch_intent")
        }
    }

    private fun findPackage(ctx: Context, query: String): String? {
        val q = query.lowercase().trim()
        // 1. Точный package name
        val pm = ctx.packageManager
        try {
            if (pm.getLaunchIntentForPackage(q) != null) return q
        } catch (_: Exception) {}
        // 2. По label через PackageManager
        val intent = Intent(Intent.ACTION_MAIN).apply { addCategory(Intent.CATEGORY_LAUNCHER) }
        val apps = pm.queryIntentActivities(intent, 0)
        for (info in apps) {
            val label = info.loadLabel(pm).toString().lowercase()
            if (label == q || label.contains(q) || q.contains(label)) {
                return info.activityInfo.packageName
            }
        }
        return null
    }

    private fun dial(ctx: Context, number: String): JSONObject {
        if (number.isBlank()) return err("missing number")
        val uri = Uri.parse("tel:$number")
        val intent = Intent(Intent.ACTION_DIAL, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
        return ok(mapOf("message" to "dialer opened"))
    }

    private fun sendSms(ctx: Context, number: String, text: String): JSONObject {
        if (number.isBlank() || text.isBlank()) return err("need number and text")
        val uri = Uri.parse("smsto:$number")
        val intent = Intent(Intent.ACTION_SENDTO, uri).apply {
            putExtra("sms_body", text)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
        return ok(mapOf("message" to "SMS draft ready, user must tap SEND"))
    }

    private fun setAlarm(ctx: Context, hour: Int, minute: Int, label: String): JSONObject {
        val i = Intent(AlarmClock.ACTION_SET_ALARM).apply {
            putExtra(AlarmClock.EXTRA_HOUR, hour)
            putExtra(AlarmClock.EXTRA_MINUTES, minute)
            if (label.isNotBlank()) putExtra(AlarmClock.EXTRA_MESSAGE, label)
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(i)
        return ok(mapOf("message" to "alarm set for ${"%02d:%02d".format(hour, minute)}"))
    }

    private fun setTimer(ctx: Context, seconds: Int): JSONObject {
        if (seconds <= 0) return err("seconds must be > 0")
        val i = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(i)
        return ok(mapOf("message" to "timer started for $seconds seconds"))
    }

    private fun navigate(ctx: Context, destination: String): JSONObject {
        if (destination.isBlank()) return err("missing destination")
        val uri = Uri.parse("google.navigation:q=${Uri.encode(destination)}")
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
        return ok(mapOf("message" to "navigation opened"))
    }

    private fun webSearch(ctx: Context, query: String): JSONObject {
        if (query.isBlank()) return err("missing query")
        val uri = Uri.parse("https://www.google.com/search?q=${Uri.encode(query)}")
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
        return ok(mapOf("message" to "search opened"))
    }

    private fun openUrl(ctx: Context, url: String): JSONObject {
        if (url.isBlank()) return err("missing url")
        // Принимаем http(s):// и localhost-стиль ссылки на Tailscale-IP.
        val normalized = if (url.startsWith("http://") || url.startsWith("https://")) url else "http://$url"
        return try {
            val uri = Uri.parse(normalized)
            val intent = Intent(Intent.ACTION_VIEW, uri).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(intent)
            ok(mapOf("message" to "URL opened"))
        } catch (e: Exception) {
            err("invalid_url")
        }
    }

    private fun setVolume(ctx: Context, level: Any?): JSONObject {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val cur = am.getStreamVolume(AudioManager.STREAM_MUSIC)
        val newVol = when (level) {
            is Int -> (max * level / 100).coerceIn(0, max)
            is String -> when (level.lowercase()) {
                "max", "full" -> max
                "mute", "off", "zero" -> 0
                "up" -> (cur + max / 5).coerceAtMost(max)
                "down" -> (cur - max / 5).coerceAtLeast(0)
                else -> level.toIntOrNull()?.let { (max * it / 100).coerceIn(0, max) }
                    ?: return err("bad_level")
            }
            else -> return err("missing level")
        }
        am.setStreamVolume(AudioManager.STREAM_MUSIC, newVol, AudioManager.FLAG_SHOW_UI)
        return ok(mapOf("volume_percent" to (newVol * 100 / max)))
    }

    private fun setBrightness(ctx: Context, level: Any?): JSONObject {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.System.canWrite(ctx)) {
            val i = Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS).apply {
                data = Uri.parse("package:${ctx.packageName}")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(i)
            return err("need WRITE_SETTINGS permission, opened settings page")
        }
        val cr = ctx.contentResolver
        val cur = try { Settings.System.getInt(cr, Settings.System.SCREEN_BRIGHTNESS) } catch (_: Exception) { 128 }
        val target = when (level) {
            is Int -> (255 * level / 100).coerceIn(0, 255)
            is String -> when (level.lowercase()) {
                "max", "full" -> 255
                "min", "low" -> 10
                "up" -> (cur + 50).coerceAtMost(255)
                "down" -> (cur - 50).coerceAtLeast(0)
                else -> level.toIntOrNull()?.let { (255 * it / 100).coerceIn(0, 255) }
                    ?: return err("bad_level")
            }
            else -> return err("missing level")
        }
        Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS, target)
        return ok(mapOf("brightness_percent" to (target * 100 / 255)))
    }

    private fun pressHome(ctx: Context): JSONObject {
        val i = Intent(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_HOME)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(i)
        return ok(mapOf("message" to "home"))
    }

    private fun status(ctx: Context): JSONObject {
        val a11y = HermesAccessibilityService.instance != null
        return ok(mapOf(
            "model" to Build.MODEL,
            "android" to Build.VERSION.SDK_INT,
            "accessibility_enabled" to a11y,
            "can_write_settings" to (Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.System.canWrite(ctx)),
            "all_files_access" to PhoneFiles.hasAllFilesAccess(),
        ))
    }

    /** Открывает системные настройки для предоставления MANAGE_EXTERNAL_STORAGE. */
    private fun requestAllFilesAccess(ctx: Context): JSONObject {
        if (PhoneFiles.hasAllFilesAccess()) {
            return ok(mapOf("message" to "already granted"))
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return ok(mapOf("message" to "not needed on Android < 11; standard READ/WRITE_EXTERNAL_STORAGE is enough"))
        }
        try {
            val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
                data = Uri.parse("package:${ctx.packageName}")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(intent)
            return ok(mapOf("message" to "opened settings — user must toggle 'Allow all files access' for Тройка"))
        } catch (e: Exception) {
            // Fallback на общий экран всех приложений с этим permission
            try {
                val intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                ctx.startActivity(intent)
                return ok(mapOf("message" to "opened generic all-files settings — find Тройка in the list"))
            } catch (e2: Exception) {
                return err("cannot_open_settings")
            }
        }
    }

    // ---- Server-initiated notification + TTS -----------------------------

    private const val NOTIFY_CHANNEL_ID: String = "hermes_push"
    private const val NOTIFY_ID_BASE: Int = 2001

    private fun notifyUser(ctx: Context, text: String, speak: Boolean, title: String): JSONObject {
        if (text.isBlank()) return err("missing text")

        // 1. Шторка: показать notification (отдельный канал от foreground service)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val nm = ctx.getSystemService(NotificationManager::class.java)
                if (nm != null && nm.getNotificationChannel(NOTIFY_CHANNEL_ID) == null) {
                    val ch = NotificationChannel(
                        NOTIFY_CHANNEL_ID,
                        "Сообщения от Тройки",
                        NotificationManager.IMPORTANCE_HIGH,
                    ).apply {
                        description = "Когда Тройка инициирует разговор сама"
                        enableVibration(true)
                    }
                    nm.createNotificationChannel(ch)
                }
            }
            // Тап по нотификации открывает приложение
            val openIntent = Intent(ctx, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            val pendingFlags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE
            } else android.app.PendingIntent.FLAG_UPDATE_CURRENT
            val pi = android.app.PendingIntent.getActivity(ctx, 0, openIntent, pendingFlags)

            val notif = NotificationCompat.Builder(ctx, NOTIFY_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build()
            val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val notifId = NOTIFY_ID_BASE + (System.currentTimeMillis() % 1000).toInt()
            nm.notify(notifId, notif)
        } catch (e: Exception) {
            Log.e(TAG, "Notification delivery failed")
        }

        // 2. Озвучка через EdgeTTS — в фоне, не блокируем WS-ответ
        if (speak) {
            val prefs = ctx.getSharedPreferences(HermesListenerService.PREFS, Context.MODE_PRIVATE)
            val url = prefs.getString(HermesListenerService.PREF_URL, null)
            val key = prefs.getString(HermesListenerService.PREF_KEY, "") ?: ""
            val voice = prefs.getString("flutter.hermes_edge_voice", "ru-RU-SvetlanaNeural")
                ?: "ru-RU-SvetlanaNeural"
            val rate = (prefs.all["flutter.hermes_voice_rate"] as? Number)?.toDouble() ?: 1.0
            val pitch = (prefs.all["flutter.hermes_voice_pitch"] as? Number)?.toInt() ?: 0
            val vol = (prefs.all["flutter.hermes_voice_volume"] as? Number)?.toInt() ?: 0
            if (!url.isNullOrBlank()) {
                Thread {
                    try {
                        val player = EdgeTtsPlayer(ctx.applicationContext, url, key, voice, rate, pitch, vol)
                        player.speak(text) { player.stop() }
                    } catch (e: Exception) {
                        Log.e(TAG, "Notification speech failed")
                    }
                }.apply { name = "NotifyUserTTS" }.start()
            } else {
                Log.w(TAG, "notify: server URL not configured, skip TTS")
            }
        }

        return ok(mapOf("notified" to true, "spoke" to speak))
    }

    // ---- AccessibilityService-команды ------------------------------------

    private fun accessibility(block: (HermesAccessibilityService) -> JSONObject): JSONObject {
        val svc = HermesAccessibilityService.instance
            ?: return err("accessibility_disabled: ask user to enable Тройка in Settings → Accessibility")
        return try {
            block(svc)
        } catch (e: Exception) {
            err("a11y_error")
        }
    }

    // ---- helpers ---------------------------------------------------------

    private fun ok(extra: Map<String, Any?> = emptyMap()): JSONObject {
        return JSONObject().apply {
            put("ok", true)
            for ((k, v) in extra) put(k, v)
        }
    }

    private fun err(msg: String): JSONObject = JSONObject().apply {
        put("ok", false)
        put("error", msg)
    }
}
