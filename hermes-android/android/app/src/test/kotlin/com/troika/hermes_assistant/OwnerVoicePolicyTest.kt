package com.troika.hermes_assistant

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.sqrt

class OwnerVoicePolicyTest {
    private fun voice(first: Double, second: Double = 0.0) = DoubleArray(128).also { it[0] = first; it[1] = second }
    @Test fun acceptsThreeConsistentLongSamples() {
        val samples = mutableListOf<DoubleArray>()
        listOf(voice(1.0), voice(0.99, 0.01), voice(0.98, 0.02)).forEach {
            assertTrue(OwnerVoicePolicy.acceptsSample(samples, it, 400)); samples.add(it)
        }
        assertFalse(OwnerVoicePolicy.acceptsSample(samples, voice(1.0), 400))
        assertTrue(OwnerVoicePolicy.matches(samples, voice(0.95, 0.05), 400))
    }
    @Test fun rejectsAnotherSpeakerInEnrollmentAndVerification() {
        assertFalse(OwnerVoicePolicy.acceptsSample(listOf(voice(1.0)), voice(0.0, 1.0), 500))
        assertFalse(OwnerVoicePolicy.matches(List(3) { voice(1.0) }, voice(0.0, 1.0), 500))
    }
    @Test fun rejectsShortSamplesEvenWhenVectorMatches() {
        assertFalse(OwnerVoicePolicy.acceptsSample(emptyList(), voice(1.0), 399))
        assertFalse(OwnerVoicePolicy.matches(List(3) { voice(1.0) }, voice(1.0), 399))
    }
    @Test fun refusesMissingOrIncompleteProfile() {
        for (count in 0..2) assertFalse(OwnerVoicePolicy.matches(List(count) { voice(1.0) }, voice(1.0), 500))
    }
    @Test fun rejectsInvalidVectors() {
        val invalid = listOf(DoubleArray(0), DoubleArray(127), DoubleArray(128),
            voice(Double.NaN), voice(Double.POSITIVE_INFINITY), voice(Double.MAX_VALUE))
        invalid.forEach { vector ->
            assertFalse(OwnerVoicePolicy.valid(vector))
            assertFalse(OwnerVoicePolicy.acceptsSample(emptyList(), vector, 500))
            assertFalse(OwnerVoicePolicy.matches(List(3) { voice(1.0) }, vector, 500))
        }
    }
    @Test fun medianRequiresTwoMatchingSamples() {
        assertTrue(OwnerVoicePolicy.matches(listOf(voice(1.0), voice(1.0), voice(0.0, 1.0)), voice(1.0), 500))
        assertFalse(OwnerVoicePolicy.matches(listOf(voice(1.0), voice(0.0, 1.0), voice(0.0, 1.0)), voice(1.0), 500))
    }
    @Test fun scoreIsInvariantToVolumeScaling() {
        assertEquals(1.0, OwnerVoicePolicy.cosine(voice(1.0), voice(20.0)), 1e-10)
        assertTrue(OwnerVoicePolicy.matches(List(3) { voice(1.0) }, voice(0.001), 400))
    }
    @Test fun rejectsJustBelowThreshold() {
        val below = voice(0.7499, sqrt(1.0 - 0.7499 * 0.7499))
        assertFalse(OwnerVoicePolicy.matches(List(3) { voice(1.0) }, below, 500))
    }
}
