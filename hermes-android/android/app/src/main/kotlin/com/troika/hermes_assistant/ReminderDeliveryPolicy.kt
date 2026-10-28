package com.troika.hermes_assistant

/** Server timestamps are UTC instants, independent of the device's time zone. */
internal object ReminderDeliveryPolicy {
    const val MAX_FIRE_AT_SECONDS = 32_503_680_000.0
    private val ownerPattern = Regex("usr_[0-9a-f]{32}")
    private val idPattern = Regex("msg_[0-9a-f]{32}")

    data class Reminder(
        val id: String,
        val fireAtSeconds: Double,
        val title: String,
        val body: String,
        val availableAt: String,
    ) {
        val spokenText: String get() = body.ifBlank { title }.take(1000)
    }

    fun validate(owner: String, reminders: List<Reminder>) {
        require(ownerPattern.matches(owner))
        require(reminders.size <= 200)
        val ids = mutableSetOf<String>()
        reminders.forEach {
            require(idPattern.matches(it.id) && ids.add(it.id))
            require(it.fireAtSeconds.isFinite() && it.fireAtSeconds in 0.0..MAX_FIRE_AT_SECONDS)
        }
    }

    fun matchesIdentity(savedOrigin: String?, savedRevision: Long, currentOrigin: String,
        currentRevision: Long, hasCredential: Boolean): Boolean {
        if (!hasCredential || currentOrigin.isBlank()) return false
        // Preserve an authenticated old installation's offline snapshot until its next sync.
        return savedOrigin == null || (savedOrigin == currentOrigin && savedRevision == currentRevision)
    }

    fun retiredIds(previous: List<Reminder>, next: List<Reminder>): Set<String> {
        val current = next.associateBy { it.id }
        return previous.filter { old ->
            val replacement = current[old.id]
            replacement == null || old.title != replacement.title || old.body != replacement.body ||
                old.availableAt != replacement.availableAt
        }.mapTo(mutableSetOf()) { it.id }
    }

    fun alarmTimeMillis(reminder: Reminder, nowMillis: Long): Long =
        maxOf((reminder.fireAtSeconds * 1000).toLong(), nowMillis + 500)

    fun isDue(reminder: Reminder, nowMillis: Long): Boolean =
        nowMillis >= (reminder.fireAtSeconds * 1000).toLong()
}
