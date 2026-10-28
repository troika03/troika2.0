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
    private val syncTickets = ReminderSyncTickets<NativeAccountSession.Identity>()

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun rows(context: Context): JSONArray = try {
        JSONArray(prefs(context).getString("rows", "[]"))
    } catch (_: Exception) { JSONArray() }

    private fun record(row: JSONObject) = ReminderDeliveryPolicy.Reminder(
        row.getString("id"), row.getDouble("fire_at"), row.optString("title"),
        row.optString("body"), row.optString("available_at"))

    private fun records(rows: JSONArray): List<ReminderDeliveryPolicy.Reminder> =
        (0 until rows.length()).map { record(rows.getJSONObject(it)) }

    private fun accountValue(account: android.content.SharedPreferences, name: String): String =
        (account.getString("flutter.troika_$name", null) ?:
            account.getString("flutter.hermes_$name", null)).orEmpty().trim()

    private fun identityMatches(context: Context): Boolean {
        val saved = prefs(context)
        val account = context.getSharedPreferences(HermesListenerService.PREFS, Context.MODE_PRIVATE)
        return ReminderDeliveryPolicy.matchesIdentity(saved.getString("identity_origin", null),
            saved.getLong("identity_revision", 0), accountValue(account, "server_url").trimEnd('/'),
            account.getLong(NativeAccountSession.IDENTITY_REVISION, 0), accountValue(account, "api_key").isNotBlank())
    }

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

    @Synchronized fun beginSync(context: Context, expectedIdentity: NativeAccountSession.Identity? = null): Long? {
        val identity = expectedIdentity ?: NativeAccountSession.snapshot(context) ?: return null
        if (!NativeAccountSession.current(context, identity)) return null
        return syncTickets.begin(identity)
    }

    @Synchronized fun applySync(context: Context, snapshot: JSONObject, ticket: Long): Map<String, Boolean>? {
        val identity = syncTickets.consume(ticket) { NativeAccountSession.current(context, it) } ?: return null
        return applySnapshot(context, snapshot, identity)
    }

    @Synchronized fun rejectSync(context: Context, ticket: Long): Boolean {
        syncTickets.consume(ticket) { NativeAccountSession.current(context, it) } ?: return false
        clear(context)
        return true
    }

    @Synchronized fun sync(context: Context, snapshot: JSONObject): Map<String, Boolean> {
        val ticket = requireNotNull(beginSync(context))
        return requireNotNull(applySync(context, snapshot, ticket))
    }

    private fun applySnapshot(context: Context, snapshot: JSONObject,
        identity: NativeAccountSession.Identity): Map<String, Boolean> {
        val owner = snapshot.optString("owner_id")
        val enabled = snapshot.get("reminders_enabled")
        require(enabled is Boolean)
        val incoming = snapshot.getJSONArray("reminders")
        val next = if (enabled) incoming else JSONArray()
        require(next.length() <= 200)
        val nextRecords = records(next)
        ReminderDeliveryPolicy.validate(owner, nextRecords)
        val preferences = prefs(context)
        if (preferences.getString("owner", "") != owner) clear(context)
        val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val previous = rows(context)
        for (i in 0 until previous.length()) alarms.cancel(pending(context, previous.getJSONObject(i).getString("id")))
        val nextIds = nextRecords.mapTo(mutableSetOf()) { it.id }
        val retired = ReminderDeliveryPolicy.retiredIds(records(previous), nextRecords) +
            (preferences.getStringSet("fired", emptySet()) ?: emptySet()).filterNot { it in nextIds }
        for (id in retired) manager.cancel(id, 1)
        preferences.edit().putString("owner", owner).putString("rows", next.toString())
            .putLong("identity_revision", identity.generation)
            .putString("identity_origin", identity.serverUrl).commit()
        ReminderVoiceService.remindersChanged()
        reschedule(context)
        return status(context)
    }

    @Synchronized fun clear(context: Context) {
        syncTickets.clear()
        context.stopService(Intent(context, ReminderVoiceService::class.java))
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
        if (!identityMatches(context)) return
        val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val saved = rows(context)
        val fired = prefs(context).getStringSet("fired", emptySet()) ?: emptySet()
        for (row in records(saved)) {
            val id = row.id
            if (fired.contains(id)) continue
            val time = ReminderDeliveryPolicy.alarmTimeMillis(row, System.currentTimeMillis())
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
        if (intent.action != FIRE || !identityMatches(context)) return
        val id = intent.getStringExtra("id") ?: return
        val saved = rows(context)
        val fired = (prefs(context).getStringSet("fired", emptySet()) ?: emptySet()).toMutableSet()
        if (fired.contains(id) || status(context)["notifications_enabled"] != true) return
        for (i in 0 until saved.length()) {
            val row = saved.getJSONObject(i)
            if (row.optString("id") != id) continue
            if (!ReminderDeliveryPolicy.isDue(record(row), System.currentTimeMillis())) {
                reschedule(context)
                return
            }
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
            try { manager.notify(id, 1, notification) } catch (_: SecurityException) { return }
            fired.add(id)
            // IDs contain no message contents; retain deduplication across syncs.
            prefs(context).edit().putStringSet("fired", fired).commit()
            try {
                ContextCompat.startForegroundService(context, Intent(context, ReminderVoiceService::class.java)
                    .putExtra("owner", prefs(context).getString("owner", ""))
                    .putExtra("id", id))
            } catch (_: Exception) {
                // Notification delivery remains useful if the OS blocks speech.
            }
            return
        }
    }

    @Synchronized fun spokenText(context: Context, owner: String, id: String): String {
        if (!identityMatches(context) || owner.isBlank() || prefs(context).getString("owner", "") != owner ||
            !(prefs(context).getStringSet("fired", emptySet()) ?: emptySet()).contains(id)) return ""
        val saved = rows(context)
        for (i in 0 until saved.length()) {
            val row = saved.getJSONObject(i)
            if (row.optString("id") == id) {
                return record(row).spokenText
            }
        }
        return ""
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
