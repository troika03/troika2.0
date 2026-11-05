package com.troika.hermes_assistant

import kotlin.math.sqrt

/** Conservative speaker filtering, not authentication or replay protection. */
internal object OwnerVoicePolicy {
    const val DIMENSIONS = 128
    const val REQUIRED_SAMPLES = 3
    const val MIN_FRAMES = 400
    const val MIN_COSINE = 0.75

    fun valid(vector: DoubleArray): Boolean = vector.size == DIMENSIONS &&
        vector.all { it.isFinite() } && vector.sumOf { it * it }.let { it.isFinite() && it > 1e-12 }

    fun cosine(left: DoubleArray, right: DoubleArray): Double {
        if (!valid(left) || !valid(right)) return -1.0
        val norm = sqrt(left.sumOf { it * it }) * sqrt(right.sumOf { it * it })
        return left.indices.sumOf { left[it] * right[it] } / norm
    }

    fun acceptsSample(samples: List<DoubleArray>, vector: DoubleArray, frames: Int): Boolean =
        frames >= MIN_FRAMES && valid(vector) && samples.size < REQUIRED_SAMPLES &&
            samples.all { cosine(it, vector) >= MIN_COSINE }

    fun matches(samples: List<DoubleArray>, vector: DoubleArray, frames: Int): Boolean {
        if (frames < MIN_FRAMES || samples.size != REQUIRED_SAMPLES || !valid(vector) ||
            samples.any { !valid(it) }) return false
        return samples.map { cosine(it, vector) }.sorted()[1] >= MIN_COSINE
    }
}
