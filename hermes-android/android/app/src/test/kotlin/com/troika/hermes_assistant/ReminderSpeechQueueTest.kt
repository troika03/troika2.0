package com.troika.hermes_assistant

import org.junit.Assert.*
import org.junit.Test

class ReminderSpeechQueueTest {
    private val first = ReminderSpeechQueue.Reminder("owner-a", "first", "Первое дело.")
    private val second = ReminderSpeechQueue.Reminder("owner-a", "second", "Второе дело.")

    @Test fun duplicateAlarmCannotEnqueueTheSameSpeechTwice() {
        val queue = ReminderSpeechQueue()
        queue.enqueue(first)
        queue.enqueue(first)
        val playback = queue.next { true }!!
        queue.enqueue(first)
        assertTrue(queue.finish(playback))
        assertNull(queue.next { true })
        assertTrue(queue.isEmpty)
    }

    @Test fun retractStopsOnlyTheStaleSpeechAndLateCompletionCannotSkipTheNextReminder() {
        val queue = ReminderSpeechQueue()
        queue.enqueue(first)
        queue.enqueue(second)
        val old = queue.next { true }!!
        assertTrue(queue.reconcile { it.id != first.id })
        val current = queue.next { true }!!
        assertEquals(second, current.reminder)
        assertFalse(queue.finish(old))
        assertEquals(current, queue.active)
        assertTrue(queue.finish(current))
        assertTrue(queue.isEmpty)
    }

    @Test fun accountClearInvalidatesQueuedSpeechAndLateAuthentication() {
        val queue = ReminderSpeechQueue()
        queue.enqueue(first)
        queue.enqueue(second)
        val old = queue.next { true }!!
        queue.clear()
        val newOwner = first.copy(owner = "owner-b")
        queue.enqueue(newOwner)
        val current = queue.next { true }!!
        assertNotEquals(old.generation, current.generation)
        assertFalse(queue.finish(old))
        assertEquals(newOwner, queue.active!!.reminder)
    }

    @Test fun retractedQueuedReminderNeverStartsAndUnchangedSnapshotKeepsActiveSpeech() {
        val queue = ReminderSpeechQueue()
        queue.enqueue(first)
        queue.enqueue(second)
        val active = queue.next { true }!!
        assertFalse(queue.reconcile { it.id == first.id })
        assertEquals(active, queue.active)
        queue.finish(active)
        assertNull(queue.next { true })
    }
}
