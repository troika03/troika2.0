package com.troika.hermes_assistant

import org.junit.Assert.*
import org.junit.Test

class ReminderSyncTicketsTest {
    private data class Identity(val origin: String, val revision: Int)
    private val identity = Identity("https://synthetic.example.invalid", 1)

    @Test fun olderNativeSnapshotCannotUndoANewerFlutterCancellation() {
        val tickets = ReminderSyncTickets<Identity>()
        val oldNative = tickets.begin(identity)
        val cancellation = tickets.begin(identity)
        assertEquals(identity, tickets.consume(cancellation) { true })
        assertNull(tickets.consume(oldNative) { true })
    }

    @Test fun newerNativeRequestWinsEvenWhenItsResponseArrivesFirst() {
        val tickets = ReminderSyncTickets<Identity>()
        val first = tickets.begin(identity)
        val second = tickets.begin(identity)
        assertNull(tickets.consume(first) { true })
        assertEquals(identity, tickets.consume(second) { true })
        assertNull(tickets.consume(second) { true })
    }

    @Test fun accountSwitchCannotRebindAnOldSnapshotToTheNewAccount() {
        val tickets = ReminderSyncTickets<Identity>()
        val old = tickets.begin(identity)
        val newIdentity = identity.copy(revision = 2)
        assertNull(tickets.consume(old) { it == newIdentity })
        val current = tickets.begin(newIdentity)
        assertEquals(newIdentity, tickets.consume(current) { it == newIdentity })
    }

    @Test fun clearInvalidatesAllPendingSnapshotCallbacks() {
        val tickets = ReminderSyncTickets<Identity>()
        val old = tickets.begin(identity)
        tickets.clear()
        assertNull(tickets.consume(old) { true })
        val current = tickets.begin(identity)
        assertNotEquals(old, current)
        assertEquals(identity, tickets.consume(current) { true })
    }
}
