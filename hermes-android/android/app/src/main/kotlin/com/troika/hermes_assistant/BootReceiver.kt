package com.troika.hermes_assistant

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

/**
 * Запускает HermesListenerService автоматически после перезагрузки телефона.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action == Intent.ACTION_BOOT_COMPLETED ||
            action == Intent.ACTION_LOCKED_BOOT_COMPLETED ||
            action == "android.intent.action.QUICKBOOT_POWERON"
        ) {
            if (action != Intent.ACTION_LOCKED_BOOT_COMPLETED) ReminderScheduler.reschedule(context)
            // После reboot восстанавливаем только явно включённое пользователем
            // фоновое пробуждение. Другие старые настройки не должны сами
            // активировать микрофонный foreground service.
            val prefs = context.getSharedPreferences(
                HermesListenerService.PREFS, Context.MODE_PRIVATE
            )
            val wakeEnabled = prefs.getBoolean(
                HermesListenerService.PREF_WAKE_WORD_ENABLED, false
            )
            if (!wakeEnabled) {
                android.util.Log.i("BootReceiver", "Skipping start — background wake is off")
                return
            }
            val url = prefs.getString(HermesListenerService.PREF_URL, null)
            if (url.isNullOrBlank()) {
                android.util.Log.w("BootReceiver", "Skipping start — no server URL yet")
                return
            }
            val svc = Intent(context, HermesListenerService::class.java).apply {
                this.action = HermesListenerService.ACTION_START
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(svc)
            } else {
                context.startService(svc)
            }
        }
    }
}
