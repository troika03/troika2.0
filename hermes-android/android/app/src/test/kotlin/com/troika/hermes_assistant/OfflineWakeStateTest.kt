package com.troika.hermes_assistant

import org.junit.Assert.*
import org.junit.Test

class OfflineWakeStateTest {
    @Test fun duplicateStartsCannotQueueAnotherRecorderDuringModelLoad() {
        val state = OfflineWakeState()
        val loading = state.start()!!
        assertNull(state.start())
        assertTrue(state.isCurrent(loading))
    }

    @Test fun stopInvalidatesModelLoadReadyWakeAndErrorCallbacks() {
        val state = OfflineWakeState()
        val old = state.start()!!
        assertSame(old, state.stop())
        assertFalse(state.isCurrent(old))
        assertFalse(state.finish(old))
        val next = state.start()!!
        assertTrue(state.isCurrent(next))
        assertFalse(state.finish(old))
        assertTrue(state.isCurrent(next))
    }

    @Test fun oneTerminalEventAllowsAnotherSessionButCannotEndIt() {
        val state = OfflineWakeState()
        val old = state.start()!!
        assertTrue(state.finish(old))
        assertFalse(state.finish(old))
        val next = state.start()!!
        assertFalse(state.finish(old))
        assertTrue(state.finish(next))
    }

    @Test fun closePreventsAnyLateLoadFromStartingRecording() {
        val state = OfflineWakeState()
        val old = state.start()!!
        assertSame(old, state.close())
        assertFalse(state.isCurrent(old))
        assertFalse(state.finish(old))
        assertNull(state.start())
        assertNull(state.close())
        assertNull(state.stop())
        assertNull(state.start())
    }

    @Test fun onlyExactRussianWakeWordMatches() {
        val matcher = OfflineWakeMatcher()
        assertFalse(matcher.accept("стройка", true))
        assertFalse(matcher.accept("тройками", true))
        assertFalse(matcher.accept("тройкадва", true))
        assertFalse(matcher.accept("[unk]", true))
        assertFalse(matcher.accept("", true))
        assertTrue(matcher.accept("Тройка!", true))
        assertTrue(matcher.accept("эй тройка", true))
    }

    @Test fun aPartialNeedsConfirmationAndUnrelatedSpeechResetsIt() {
        val matcher = OfflineWakeMatcher()
        assertFalse(matcher.accept("тройка", false))
        assertFalse(matcher.accept("[unk]", false))
        assertFalse(matcher.accept("тройка", false))
        assertTrue(matcher.accept("тройка", false))
    }

    @Test fun finalWakeDoesNotWaitForAnotherUtterance() {
        val matcher = OfflineWakeMatcher()
        assertFalse(matcher.accept("тро", false))
        assertTrue(matcher.accept("тройка", true))
    }

    @Test fun oversizedRecognitionCannotKeepAPartialCandidate() {
        val matcher = OfflineWakeMatcher()
        assertFalse(matcher.accept("тройка", false))
        assertFalse(matcher.accept("тройка ".repeat(100), false))
        assertFalse(matcher.accept("тройка", false))
    }
}
