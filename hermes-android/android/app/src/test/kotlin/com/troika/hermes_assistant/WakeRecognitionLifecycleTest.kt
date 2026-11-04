package com.troika.hermes_assistant

import org.junit.Assert.*
import org.junit.Test

class WakeRecognitionLifecycleTest {
    private fun start(cycle: WakeRecognitionLifecycle): Long {
        val ticket = cycle.schedule()!!
        assertTrue(cycle.start(ticket))
        return ticket
    }

    @Test fun repeatedStartsCannotOverlapPendingOrActiveRecognition() {
        val cycle = WakeRecognitionLifecycle()
        val ticket = cycle.schedule()!!
        assertNull(cycle.schedule())
        assertTrue(cycle.start(ticket))
        assertFalse(cycle.start(ticket))
        assertNull(cycle.schedule())
        assertTrue(cycle.isCurrent(ticket))
    }

    @Test fun pauseInvalidatesQueuedStartAndLateCallbacks() {
        val cycle = WakeRecognitionLifecycle()
        val queued = cycle.schedule()!!
        cycle.invalidate()
        assertFalse(cycle.start(queued))
        assertNull(cycle.complete(queued))
        val current = start(cycle)
        assertTrue(cycle.isCurrent(current))
        assertFalse(cycle.isCurrent(queued))
    }

    @Test fun oldErrorCannotEndOrRestartANewerAttempt() {
        val cycle = WakeRecognitionLifecycle()
        val old = start(cycle)
        cycle.invalidate()
        val current = start(cycle)
        assertNull(cycle.complete(old, WakeRecognitionLifecycle.Failure.BUSY))
        assertNull(cycle.schedule())
        assertTrue(cycle.isCurrent(current))
        assertEquals(800L, cycle.complete(current))
    }

    @Test fun duplicateCompletionCannotQueueTwoRestarts() {
        val cycle = WakeRecognitionLifecycle()
        val ticket = start(cycle)
        assertEquals(800L, cycle.complete(ticket))
        assertNull(cycle.complete(ticket, WakeRecognitionLifecycle.Failure.BUSY))
        val next = cycle.schedule()!!
        assertNull(cycle.schedule())
        assertFalse(cycle.isCurrent(ticket))
        assertTrue(cycle.start(next))
    }

    @Test fun busyErrorsBackOffAndAQuietCompletedAttemptResetsTheDelay() {
        val cycle = WakeRecognitionLifecycle()
        assertEquals(1500L, cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.BUSY))
        assertEquals(3000L, cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.BUSY))
        assertEquals(6000L, cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.BUSY))
        assertEquals(800L, cycle.complete(start(cycle)))
        assertEquals(1500L, cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.BUSY))
    }

    @Test fun audioFailuresHaveABoundedBackoffInsteadOfAFastLoop() {
        val cycle = WakeRecognitionLifecycle()
        assertEquals(2000L, cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.AUDIO))
        repeat(8) {
            val delay = cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.AUDIO)!!
            assertTrue(delay in 4000L..30_000L)
        }
        assertEquals(30_000L, cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.AUDIO))
    }

    @Test fun missingPermissionCannotBeRetriedByWatchdogOrResume() {
        val cycle = WakeRecognitionLifecycle()
        assertNull(cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.PERMISSION))
        repeat(3) {
            assertNull(cycle.schedule())
            cycle.invalidate()
        }
        cycle.retryAfterExplicitStart()
        assertTrue(cycle.isCurrent(start(cycle)))
    }

    @Test fun unavailableLanguageRequiresAnExplicitRetry() {
        val cycle = WakeRecognitionLifecycle()
        assertNull(cycle.complete(start(cycle), WakeRecognitionLifecycle.Failure.UNAVAILABLE))
        assertNull(cycle.schedule())
        cycle.retryAfterExplicitStart()
        val current = start(cycle)
        assertEquals(800L, cycle.complete(current))
    }

    @Test fun repeatedServiceStartsDoNotResetAnActiveAttempt() {
        val cycle = WakeRecognitionLifecycle()
        val ticket = start(cycle)
        cycle.retryAfterExplicitStart()
        assertNull(cycle.schedule())
        assertTrue(cycle.isCurrent(ticket))
    }

    @Test fun stopInvalidatesBothActiveAndPendingGenerations() {
        val cycle = WakeRecognitionLifecycle()
        val active = start(cycle)
        cycle.invalidate()
        assertFalse(cycle.isCurrent(active))
        assertNull(cycle.complete(active))
        val queued = cycle.schedule()!!
        cycle.invalidate()
        assertFalse(cycle.start(queued))
        assertNull(cycle.complete(queued))
    }
}
