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
            // Не стартуем без сохранённого URL — иначе сервис будет крутиться вхолостую
            val prefs = context.getSharedPreferences(
                HermesListenerService.PREFS, Context.MODE_PRIVATE
            )
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
