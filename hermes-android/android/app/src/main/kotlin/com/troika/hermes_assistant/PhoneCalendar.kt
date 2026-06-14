package com.troika.hermes_assistant

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CalendarContract
import android.util.Log
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Доступ к системному календарю Android через CalendarContract.
 *
 * Работает с любым календарём, синхронизированным с устройством
 * (Samsung Calendar, Google Calendar, Outlook, локальные).
 *
 * Требует permissions READ_CALENDAR / WRITE_CALENDAR, которые
 * пользователь подтверждает в первый раз через системный диалог.
 */
object PhoneCalendar {
    private const val TAG = "PhoneCalendar"

    private val ISO = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)
    private val ISO_FALLBACK = listOf(
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US),
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US),
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US),
        SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US),
        SimpleDateFormat("yyyy-MM-dd", Locale.US),
    )

    init {
        ISO.timeZone = TimeZone.getDefault()
        ISO_FALLBACK.forEach { it.timeZone = TimeZone.getDefault() }
    }

    private fun hasReadPermission(ctx: Context): Boolean =
        ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CALENDAR) ==
            PackageManager.PERMISSION_GRANTED

    private fun hasWritePermission(ctx: Context): Boolean =
        ContextCompat.checkSelfPermission(ctx, Manifest.permission.WRITE_CALENDAR) ==
            PackageManager.PERMISSION_GRANTED

    private fun parseIso(s: String): Long? {
        if (s.isBlank()) return null
        return try {
            ISO.parse(s)?.time
        } catch (_: Exception) {
            for (fmt in ISO_FALLBACK) {
                try { return fmt.parse(s)?.time } catch (_: Exception) {}
            }
            null
        }
    }

    private fun formatIso(ms: Long): String = ISO.format(Date(ms))

    private fun permError(perm: String) = JSONObject().apply {
        put("ok", false)
        put("error", "calendar_permission_missing: ask user to grant $perm in Settings → Apps → Hermes → Permissions → Calendar (or tap 'Разрешить доступ к календарю' in Hermes settings)")
    }

    // ---- list calendars -----------------------------------------------------

    fun listCalendars(ctx: Context): JSONObject {
        if (!hasReadPermission(ctx)) return permError("READ_CALENDAR")
        val projection = arrayOf(
            CalendarContract.Calendars._ID,
            CalendarContract.Calendars.CALENDAR_DISPLAY_NAME,
            CalendarContract.Calendars.ACCOUNT_NAME,
            CalendarContract.Calendars.OWNER_ACCOUNT,
            CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL,
            CalendarContract.Calendars.IS_PRIMARY,
            CalendarContract.Calendars.VISIBLE,
        )
        val list = JSONArray()
        try {
            ctx.contentResolver.query(
                CalendarContract.Calendars.CONTENT_URI,
                projection, null, null, null
            )?.use { c ->
                while (c.moveToNext()) {
                    list.put(JSONObject().apply {
                        put("id", c.getLong(0))
                        put("display_name", c.getString(1))
                        put("account_name", c.getString(2))
                        put("owner_account", c.getString(3))
                        put("access_level", c.getInt(4))
                        put("is_primary", c.getInt(5) == 1)
                        put("visible", c.getInt(6) == 1)
                    })
                }
            }
        } catch (e: Exception) {
            return JSONObject().apply { put("ok", false); put("error", "list_calendars_failed: ${e.message}") }
        }
        return JSONObject().apply {
            put("ok", true)
            put("calendars", list)
            put("count", list.length())
        }
    }

    // ---- list events --------------------------------------------------------

    fun listEvents(ctx: Context, fromIso: String?, toIso: String?, maxResults: Int = 50): JSONObject {
        if (!hasReadPermission(ctx)) return permError("READ_CALENDAR")

        val now = System.currentTimeMillis()
        val from = parseIso(fromIso ?: "") ?: now
        val to = parseIso(toIso ?: "") ?: (now + 7L * 24 * 60 * 60 * 1000)

        val projection = arrayOf(
            CalendarContract.Events._ID,
            CalendarContract.Events.CALENDAR_ID,
            CalendarContract.Events.TITLE,
            CalendarContract.Events.DESCRIPTION,
            CalendarContract.Events.EVENT_LOCATION,
            CalendarContract.Events.DTSTART,
            CalendarContract.Events.DTEND,
            CalendarContract.Events.ALL_DAY,
            CalendarContract.Events.RRULE,
            CalendarContract.Events.EVENT_TIMEZONE,
        )

        val selection =
            "(${CalendarContract.Events.DTSTART} >= ? AND ${CalendarContract.Events.DTSTART} <= ?) " +
            "OR (${CalendarContract.Events.DTEND} >= ? AND ${CalendarContract.Events.DTSTART} <= ?)"
        val selectionArgs = arrayOf(from.toString(), to.toString(), from.toString(), to.toString())

        val list = JSONArray()
        try {
            ctx.contentResolver.query(
                CalendarContract.Events.CONTENT_URI,
                projection, selection, selectionArgs,
                "${CalendarContract.Events.DTSTART} ASC"
            )?.use { c ->
                var added = 0
                while (c.moveToNext() && added < maxResults) {
                    val start = c.getLong(5)
                    val end = if (c.isNull(6)) start else c.getLong(6)
                    list.put(JSONObject().apply {
                        put("id", c.getLong(0))
                        put("calendar_id", c.getLong(1))
                        put("title", c.getString(2) ?: "")
                        put("description", c.getString(3) ?: "")
                        put("location", c.getString(4) ?: "")
                        put("start_ms", start)
                        put("start_iso", formatIso(start))
                        put("end_ms", end)
                        put("end_iso", formatIso(end))
                        put("all_day", c.getInt(7) == 1)
                        put("rrule", c.getString(8) ?: "")
                        put("timezone", c.getString(9) ?: "")
                    })
                    added += 1
                }
            }
        } catch (e: Exception) {
            return JSONObject().apply { put("ok", false); put("error", "list_events_failed: ${e.message}") }
        }
        return JSONObject().apply {
            put("ok", true)
            put("events", list)
            put("count", list.length())
            put("from_iso", formatIso(from))
            put("to_iso", formatIso(to))
        }
    }

    // ---- create event -------------------------------------------------------

    fun createEvent(
        ctx: Context,
        title: String,
        startIso: String,
        endIso: String?,
        description: String? = null,
        location: String? = null,
        reminderMinutes: Int? = null,
        calendarId: Long? = null,
    ): JSONObject {
        if (!hasWritePermission(ctx)) return permError("WRITE_CALENDAR")
        if (!hasReadPermission(ctx)) return permError("READ_CALENDAR")

        if (title.isBlank()) {
            return JSONObject().apply { put("ok", false); put("error", "missing title") }
        }
        val start = parseIso(startIso)
            ?: return JSONObject().apply { put("ok", false); put("error", "bad start_iso: $startIso") }
        val end = parseIso(endIso ?: "") ?: (start + 60 * 60 * 1000) // default 1h

        val targetCalId = calendarId ?: findPrimaryCalendarId(ctx)
            ?: return JSONObject().apply {
                put("ok", false)
                put("error", "no_writable_calendar: user has no calendar account on the phone — ask them to add a Google/Samsung account first")
            }

        val values = ContentValues().apply {
            put(CalendarContract.Events.CALENDAR_ID, targetCalId)
            put(CalendarContract.Events.TITLE, title)
            put(CalendarContract.Events.DTSTART, start)
            put(CalendarContract.Events.DTEND, end)
            put(CalendarContract.Events.EVENT_TIMEZONE, TimeZone.getDefault().id)
            if (!description.isNullOrBlank()) put(CalendarContract.Events.DESCRIPTION, description)
            if (!location.isNullOrBlank()) put(CalendarContract.Events.EVENT_LOCATION, location)
        }

        val uri = try {
            ctx.contentResolver.insert(CalendarContract.Events.CONTENT_URI, values)
        } catch (e: SecurityException) {
            return JSONObject().apply { put("ok", false); put("error", "calendar_security: ${e.message}") }
        } catch (e: Exception) {
            return JSONObject().apply { put("ok", false); put("error", "create_failed: ${e.message}") }
        } ?: return JSONObject().apply { put("ok", false); put("error", "insert_returned_null") }

        val eventId = ContentUris.parseId(uri)

        // Add reminder if requested
        if (reminderMinutes != null && reminderMinutes > 0) {
            try {
                val rv = ContentValues().apply {
                    put(CalendarContract.Reminders.EVENT_ID, eventId)
                    put(CalendarContract.Reminders.MINUTES, reminderMinutes)
                    put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT)
                }
                ctx.contentResolver.insert(CalendarContract.Reminders.CONTENT_URI, rv)
            } catch (e: Exception) {
                Log.w(TAG, "reminder insert failed: ${e.message}")
            }
        }

        return JSONObject().apply {
            put("ok", true)
            put("event_id", eventId)
            put("calendar_id", targetCalId)
            put("title", title)
            put("start_iso", formatIso(start))
            put("end_iso", formatIso(end))
            put("message", "событие создано в системном календаре")
        }
    }

    // ---- delete event -------------------------------------------------------

    fun deleteEvent(ctx: Context, eventId: Long): JSONObject {
        if (!hasWritePermission(ctx)) return permError("WRITE_CALENDAR")
        return try {
            val uri = ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, eventId)
            val rows = ctx.contentResolver.delete(uri, null, null)
            if (rows > 0) {
                JSONObject().apply { put("ok", true); put("deleted", rows); put("event_id", eventId) }
            } else {
                JSONObject().apply { put("ok", false); put("error", "event_not_found: $eventId") }
            }
        } catch (e: Exception) {
            JSONObject().apply { put("ok", false); put("error", "delete_failed: ${e.message}") }
        }
    }

    // ---- update event -------------------------------------------------------

    fun updateEvent(
        ctx: Context,
        eventId: Long,
        title: String? = null,
        startIso: String? = null,
        endIso: String? = null,
        description: String? = null,
        location: String? = null,
    ): JSONObject {
        if (!hasWritePermission(ctx)) return permError("WRITE_CALENDAR")

        val values = ContentValues()
        if (!title.isNullOrBlank()) values.put(CalendarContract.Events.TITLE, title)
        if (!startIso.isNullOrBlank()) parseIso(startIso)?.let {
            values.put(CalendarContract.Events.DTSTART, it)
        }
        if (!endIso.isNullOrBlank()) parseIso(endIso)?.let {
            values.put(CalendarContract.Events.DTEND, it)
        }
        if (description != null) values.put(CalendarContract.Events.DESCRIPTION, description)
        if (location != null) values.put(CalendarContract.Events.EVENT_LOCATION, location)

        if (values.size() == 0) {
            return JSONObject().apply { put("ok", false); put("error", "no fields to update") }
        }

        return try {
            val uri = ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, eventId)
            val rows = ctx.contentResolver.update(uri, values, null, null)
            if (rows > 0) {
                JSONObject().apply {
                    put("ok", true)
                    put("updated", rows)
                    put("event_id", eventId)
                }
            } else {
                JSONObject().apply { put("ok", false); put("error", "event_not_found_or_no_change: $eventId") }
            }
        } catch (e: Exception) {
            JSONObject().apply { put("ok", false); put("error", "update_failed: ${e.message}") }
        }
    }

    // ---- helpers ------------------------------------------------------------

    /** Найти первый записываемый и видимый календарь — обычно primary Google. */
    private fun findPrimaryCalendarId(ctx: Context): Long? {
        val projection = arrayOf(
            CalendarContract.Calendars._ID,
            CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL,
            CalendarContract.Calendars.IS_PRIMARY,
            CalendarContract.Calendars.VISIBLE,
        )
        return try {
            ctx.contentResolver.query(
                CalendarContract.Calendars.CONTENT_URI,
                projection, null, null, null
            )?.use { c ->
                var fallback: Long? = null
                while (c.moveToNext()) {
                    val id = c.getLong(0)
                    val access = c.getInt(1)
                    val isPrimary = c.getInt(2) == 1
                    val visible = c.getInt(3) == 1
                    if (access >= CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR && visible) {
                        if (isPrimary) return@use id
                        if (fallback == null) fallback = id
                    }
                }
                fallback
            }
        } catch (e: Exception) {
            Log.w(TAG, "findPrimaryCalendarId failed: ${e.message}")
            null
        }
    }

    /** Открыть системный экран для запроса календарных permissions через MainActivity. */
    fun requestPermissions(ctx: Context): JSONObject {
        // Можем только направить пользователя на settings — runtime-разрешения
        // запрашиваются из Activity, а мы в сервисе. Hermes UI делает это сам.
        val granted = hasReadPermission(ctx) && hasWritePermission(ctx)
        return JSONObject().apply {
            put("ok", true)
            put("read_granted", hasReadPermission(ctx))
            put("write_granted", hasWritePermission(ctx))
            put("all_granted", granted)
            if (!granted) {
                put("message", "ask user to open Hermes Settings → 'Разрешить доступ к календарю'")
            }
        }
    }
}
