package com.troika.hermes_assistant

/** The scheduler serializes access; only the most recently requested snapshot may publish. */
internal class ReminderSyncTickets<I : Any> {
    private data class Ticket<I>(val id: Long, val identity: I)
    private var sequence = 0L
    private var pending: Ticket<I>? = null

    fun begin(identity: I): Long {
        val id = ++sequence
        pending = Ticket(id, identity)
        return id
    }

    fun consume(id: Long, isCurrent: (I) -> Boolean): I? {
        val ticket = pending ?: return null
        if (ticket.id != id || !isCurrent(ticket.identity)) return null
        pending = null
        return ticket.identity
    }

    fun clear() {
        sequence++
        pending = null
    }
}
