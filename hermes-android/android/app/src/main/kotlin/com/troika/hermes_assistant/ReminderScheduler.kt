package com.troika.hermes_assistant

import android.Manifest
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

/** Device-local delivery of explicitly requested, account-owned reminders. */
object ReminderScheduler {
    private const val PREFS = "troika_reminders"
    private const val CHANNEL = "troika_personal_reminders"
    private const val FIRE = "com.troika.hermes_assistant.REMINDER_FIRE"

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun rows(context: Context): JSONArray = try {
        JSONArray(prefs(context).getString("rows", "[]"))
    } catch (_: Exception) { JSONArray() }

    fun status(context: Context): Map<String, Boolean> {
        val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val permission = Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(
            context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        val channelEnabled = Build.VERSION.SDK_INT < 26 ||
            manager.getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE
        return mapOf("notifications_enabled" to (permission && manager.areNotificationsEnabled() && channelEnabled),
            "exact_alarms" to (Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms()))
    }

    private fun pending(context: Context, id: String): PendingIntent = PendingIntent.getBroadcast(
        context, 0, Intent(context, ReminderReceiver::class.java).apply {
            action = FIRE
            data = Uri.parse("troika-reminder://alarm/$id")
            putExtra("id", id)
        }, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    @Synchronized fun sync(context: Context, snapshot: JSONObject): Map<String, Boolean> {
        val owner = snapshot.optString("owner_id")
        require(owner.matches(Regex("usr_[0-9a-f]{32}")))
        val preferences = prefs(context)
        if (preferences.getString("owner", "") != owner) clear(context)
        val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val previous = rows(context)
        for (i in 0 until previous.length()) alarms.cancel(pending(context, previous.getJSONObject(i).getString("id")))
        val next = if (snapshot.optBoolean("reminders_enabled")) snapshot.optJSONArray("reminders") ?: JSONArray() else JSONArray()
        require(next.length() <= 200)
        preferences.edit().putString("owner", owner).putString("rows", next.toString()).commit()
        reschedule(context)
        return status(context)
    }

    @Synchronized fun clear(context: Context) {
        val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val previous = rows(context)
        for (i in 0 until previous.length()) {
            val id = previous.getJSONObject(i).optString("id")
            alarms.cancel(pending(context, id))
            manager.cancel(id, 1)
        }
        for (id in prefs(context).getStringSet("fired", emptySet()) ?: emptySet()) manager.cancel(id, 1)
        prefs(context).edit().clear().commit()
    }

    @Synchronized fun reschedule(context: Context) {
        val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val saved = rows(context)
        val fired = prefs(context).getStringSet("fired", emptySet()) ?: emptySet()
        for (i in 0 until saved.length()) {
            val row = saved.getJSONObject(i)
            val id = row.getString("id")
            if (!id.matches(Regex("msg_[0-9a-f]{32}")) || fired.contains(id)) continue
            val time = maxOf((row.getDouble("fire_at") * 1000).toLong(), System.currentTimeMillis() + 500)
            try {
                if (status(context)["exact_alarms"] == true) {
                    alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time, pending(context, id))
                } else {
                    alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time, pending(context, id))
                }
            } catch (_: SecurityException) {
                alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time, pending(context, id))
            }
        }
    }

    @Synchronized fun fire(context: Context, intent: Intent) {
        if (intent.action != FIRE) return
        val id = intent.getStringExtra("id") ?: return
        val saved = rows(context)
        val fired = (prefs(context).getStringSet("fired", emptySet()) ?: emptySet()).toMutableSet()
        if (fired.contains(id) || status(context)["notifications_enabled"] != true) return
        for (i in 0 until saved.length()) {
            val row = saved.getJSONObject(i)
            if (row.optString("id") != id) continue
            if (System.currentTimeMillis() + 1000 < (row.getDouble("fire_at") * 1000).toLong()) return
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "Напоминания Тройки", NotificationManager.IMPORTANCE_HIGH))
            val open = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val notification = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(row.optString("title").take(160))
                .setContentText(row.optString("body").take(1000))
                .setStyle(NotificationCompat.BigTextStyle().bigText(row.optString("body").take(1000)))
                .setContentIntent(open).setAutoCancel(true)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setCategory(NotificationCompat.CATEGORY_REMINDER)
                .setPriority(NotificationCompat.PRIORITY_HIGH).build()
            manager.notify(id, 1, notification)
            fired.add(id)
            // IDs contain no message contents; retain deduplication across syncs.
            prefs(context).edit().putStringSet("fired", fired).commit()
            return
        }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED ||
            intent.action == AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED) {
            ReminderScheduler.reschedule(context)
        } else {
            ReminderScheduler.fire(context, intent)
        }
    }
}
