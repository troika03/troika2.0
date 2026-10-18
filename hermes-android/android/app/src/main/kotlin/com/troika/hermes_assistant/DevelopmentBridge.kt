package com.troika.hermes_assistant

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

/** Local project state stays outside Android's automatic cloud backup. */
class DevelopmentBridge(context: Context, engine: FlutterEngine) {
    init {
        MethodChannel(engine.dartExecutor.binaryMessenger, "troika/development-autopilot")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "storageRoot" -> result.success(File(context.noBackupFilesDir, "development").apply { mkdirs() }.absolutePath)
                    "configure" -> {
                        val args=call.arguments as? Map<*,*> ?: emptyMap<Any,Any>()
                        val owner=args["owner"] as? String ?: ""
                        val prefs=context.getSharedPreferences("FlutterSharedPreferences", Context.MODE_PRIVATE)
                        if (owner!=prefs.getString("flutter.troika_account_email", "")) {
                            context.stopService(Intent(context,DevelopmentService::class.java))
                            result.error("account_changed","Аккаунт изменился.",null)
                        } else {
                            val state=context.getSharedPreferences("troika_development_worker",Context.MODE_PRIVATE)
                            val seen=state.getStringSet("seen:$owner",emptySet()).orEmpty() + ((args["seen"] as? List<*>)?.filterIsInstance<String>() ?: emptyList())
                            val enabled=args["enabled"]==true && prefs.getBoolean("flutter.project_background:$owner",true)
                            state.edit().putString("owner",owner).putString("server",args["server"] as? String ?: "")
                                .putString("files_root",args["files_root"] as? String ?: "")
                                .putBoolean("enabled",enabled).putStringSet("seen:$owner",seen.toList().takeLast(400).toSet()).commit()
                            if (args["foreground"]==true) DevelopmentService.uiLease() else DevelopmentService.foregroundUntil=0
                            if (enabled && args["active"]==true) {
                                try { ContextCompat.startForegroundService(context,Intent(context,DevelopmentService::class.java)) }
                                catch (_: Exception) { result.error("background_unavailable","Android не разрешил фоновое наблюдение. Откройте Тройку снова.",null); return@setMethodCallHandler }
                            } else context.stopService(Intent(context,DevelopmentService::class.java))
                            result.success(mapOf("enabled" to enabled,"seen" to seen.toList(),"running" to DevelopmentService.running))
                        }
                    }
                    "interrupt" -> { DevelopmentService.interruptReport(); result.success(null) }
                    else -> result.notImplemented()
                }
            }
    }
}
