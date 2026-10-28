package com.troika.hermes_assistant

/** Delivery ownership and callback generations without Android lifecycle dependencies. */
internal class ReminderSpeechQueue {
    data class Reminder(val owner: String, val id: String, val text: String)
    data class Playback(val reminder: Reminder, val generation: Long)

    private val pending = ArrayDeque<Reminder>()
    private var generation = 0L
    var active: Playback? = null
        private set
    val isEmpty: Boolean get() = active == null && pending.isEmpty()

    fun enqueue(reminder: Reminder) {
        if (active?.reminder != reminder && !pending.contains(reminder)) pending.addLast(reminder)
    }

    fun next(isCurrent: (Reminder) -> Boolean): Playback? {
        if (active != null) return null
        while (pending.isNotEmpty()) {
            val reminder = pending.removeFirst()
            if (isCurrent(reminder)) return Playback(reminder, ++generation).also { active = it }
        }
        return null
    }

    fun reconcile(isCurrent: (Reminder) -> Boolean): Boolean {
        pending.removeAll { !isCurrent(it) }
        if (active?.let { !isCurrent(it.reminder) } != true) return false
        active = null
        generation++
        return true
    }

    fun finish(playback: Playback): Boolean {
        if (active != playback) return false
        active = null
        return true
    }

    fun clear() {
        generation++
        active = null
        pending.clear()
    }
}
