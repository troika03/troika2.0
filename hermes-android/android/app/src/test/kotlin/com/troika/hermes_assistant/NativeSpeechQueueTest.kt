package com.troika.hermes_assistant

import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.*
import org.junit.Test

class NativeSpeechQueueTest {
    @Test(timeout = 3000)
    fun preparesNextPhraseDuringPlayback() {
        val secondPrepared = CountDownLatch(1)
        val firstPlaying = CountDownLatch(1)
        val releaseFirst = java.util.concurrent.atomic.AtomicReference<(() -> Unit)?>(null)
        val played = Collections.synchronizedList(mutableListOf<Int>())
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { text ->
                val index = when (text) { "Первая!" -> 1; "Вторая!" -> 2; else -> 3 }
                if (index == 2) secondPrepared.countDown()
                byteArrayOf(index.toByte())
            },
            playPrepared = { audio, done ->
                played.add(audio[0].toInt())
                if (audio[0].toInt() == 1) { releaseFirst.set(done); firstPlaying.countDown() } else done()
            })
        try {
            queue.add("Первая! Вторая! Третья!")
            assertTrue(firstPlaying.await(1, TimeUnit.SECONDS))
            assertTrue(secondPrepared.await(1, TimeUnit.SECONDS))
            assertEquals(listOf(1), played.toList())
            releaseFirst.get()?.invoke()
            queue.finish()
            assertEquals(listOf(1, 2, 3), played.toList())
        } finally { queue.cancel() }
    }

    @Test(timeout = 3000)
    fun firstPhraseDoesNotWaitForCompleteReply() {
        val heard = Collections.synchronizedList(mutableListOf<String>())
        val first = CountDownLatch(1)
        val queue = NativeSpeechQueue({ text, done -> heard.add(text); first.countDown(); done() }, { false })
        try {
            queue.add("[emo:")
            queue.add("joy] Привет!")
            assertTrue(first.await(1, TimeUnit.SECONDS))
            assertEquals(listOf("Привет!"), heard.toList())
            queue.add(" Число 3.")
            queue.add("14. Последняя часть")
            queue.finish()
            assertEquals(listOf("Привет!", "Число 3.14.", "Последняя часть"), heard.toList())
        } finally { queue.cancel() }
    }

    @Test(timeout = 3000)
    fun interruptionNeverStartsQueuedSpeech() {
        val interrupted = AtomicBoolean(false)
        val first = CountDownLatch(1)
        val heard = Collections.synchronizedList(mutableListOf<String>())
        val queue = NativeSpeechQueue({ text, _ -> heard.add(text); first.countDown() }, { interrupted.get() })
        try {
            queue.add("Первая! Следующая! Последняя!")
            assertTrue(first.await(1, TimeUnit.SECONDS))
            interrupted.set(true)
            queue.finish()
            assertEquals(listOf("Первая!"), heard.toList())
        } finally { queue.cancel() }
    }
}
