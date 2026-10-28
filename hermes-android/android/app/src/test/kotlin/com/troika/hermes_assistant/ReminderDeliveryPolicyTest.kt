package com.troika.hermes_assistant

import org.junit.Assert.*
import org.junit.Test

class ReminderDeliveryPolicyTest {
    private val owner = "usr_" + "a".repeat(32)
    private val firstId = "msg_" + "a".repeat(32)
    private val secondId = "msg_" + "b".repeat(32)
    private fun reminder(id: String = firstId, time: Double = 1000.0) =
        ReminderDeliveryPolicy.Reminder(id, time, "Дело", "Проверить дело.", "2026-10-28T12:00:00Z")

    @Test fun nearAndDistantRemindersRemainValidTogether() {
        val near = reminder()
        val distant = reminder(secondId, 2_000_000_000.0)
        ReminderDeliveryPolicy.validate(owner, listOf(near, distant))
        assertEquals(1_000_000L, ReminderDeliveryPolicy.alarmTimeMillis(near, 900_000))
        assertEquals(2_000_000_000_000L, ReminderDeliveryPolicy.alarmTimeMillis(distant, 900_000))
    }

    @Test fun invalidOwnerDuplicateIdAndUnboundedTimesAreRejected() {
        val invalid = listOf(Double.NaN, Double.POSITIVE_INFINITY, -1.0,
            ReminderDeliveryPolicy.MAX_FIRE_AT_SECONDS + 1)
        invalid.forEach { time ->
            assertThrows(IllegalArgumentException::class.java) {
                ReminderDeliveryPolicy.validate(owner, listOf(reminder(time = time)))
            }
        }
        assertThrows(IllegalArgumentException::class.java) {
            ReminderDeliveryPolicy.validate("usr_other", listOf(reminder()))
        }
        assertThrows(IllegalArgumentException::class.java) {
            ReminderDeliveryPolicy.validate(owner, listOf(reminder(), reminder()))
        }
    }

    @Test fun cancellationAndChangedContentRetireTheDeliveredCopy() {
        val first = reminder()
        val second = reminder(secondId)
        assertEquals(setOf(firstId), ReminderDeliveryPolicy.retiredIds(listOf(first, second), listOf(second)))
        assertEquals(setOf(firstId), ReminderDeliveryPolicy.retiredIds(listOf(first),
            listOf(first.copy(body = "Изменённое дело."))))
        assertEquals(setOf(firstId, secondId), ReminderDeliveryPolicy.retiredIds(listOf(first, second), emptyList()))
    }

    @Test fun serverMovingAnOverdueFireTimeDoesNotRetractTheDeliveredCopy() {
        val first = reminder()
        assertTrue(ReminderDeliveryPolicy.retiredIds(listOf(first),
            listOf(first.copy(fireAtSeconds = 1001.0))).isEmpty())
    }

    @Test fun wallClockRollbackDoesNotDeliverEarlyAndOverdueAlarmGetsAnotherAttempt() {
        val first = reminder()
        assertFalse(ReminderDeliveryPolicy.isDue(first, 999_999))
        assertTrue(ReminderDeliveryPolicy.isDue(first, 1_000_000))
        assertEquals(1_000_000L, ReminderDeliveryPolicy.alarmTimeMillis(first, 900_000))
        assertEquals(1_100_500L, ReminderDeliveryPolicy.alarmTimeMillis(first, 1_100_000))
    }

    @Test fun originOrAccountRevisionChangeInvalidatesOfflineDelivery() {
        val origin = "https://synthetic.example.invalid"
        assertTrue(ReminderDeliveryPolicy.matchesIdentity(origin, 2, origin, 2, true))
        assertFalse(ReminderDeliveryPolicy.matchesIdentity(origin, 2, "$origin/new", 2, true))
        assertFalse(ReminderDeliveryPolicy.matchesIdentity(origin, 2, origin, 3, true))
        assertFalse(ReminderDeliveryPolicy.matchesIdentity(origin, 2, origin, 2, false))
    }

    @Test fun legacySnapshotSurvivesUpgradeOnlyWhileCredentialsRemainPresent() {
        val origin = "https://synthetic.example.invalid"
        assertTrue(ReminderDeliveryPolicy.matchesIdentity(null, 0, origin, 0, true))
        assertFalse(ReminderDeliveryPolicy.matchesIdentity(null, 0, origin, 0, false))
        assertFalse(ReminderDeliveryPolicy.matchesIdentity(null, 0, "", 0, true))
    }
}
