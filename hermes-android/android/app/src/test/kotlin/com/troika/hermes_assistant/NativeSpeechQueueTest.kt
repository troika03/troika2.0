package com.troika.hermes_assistant

import java.util.Collections
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.*
import org.junit.Test

class NativeSpeechQueueTest {
    private class Audio(val text: String) : NativeSpeechQueue.PreparedAudio {
        val eof = AtomicBoolean(false)
        val closes = AtomicInteger(0)
        val closed = CountDownLatch(1)
        override fun close() { closes.incrementAndGet(); closed.countDown() }
    }

    private fun await(latch: CountDownLatch) = assertTrue(latch.await(2, TimeUnit.SECONDS))

    private fun awaitDespiteInterrupt(latch: CountDownLatch) {
        while (true) {
            try { latch.await(); return } catch (_: InterruptedException) {}
        }
    }

    @Test(timeout = 5000)
    fun firstPhraseStartsBeforeAudioEofOrCompleteReply() {
        val audio = Audio("Привет!")
        val started = CountDownLatch(1)
        val done = AtomicReference<(() -> Unit)?>(null)
        val beforeEof = AtomicBoolean(false)
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { audio },
            playPrepared = { handle, callback ->
                beforeEof.set(!(handle as Audio).eof.get())
                done.set(callback)
                started.countDown()
            })
        try {
            queue.add("Привет!")
            await(started)
            assertTrue(beforeEof.get())
            assertEquals(0, audio.closes.get())
            audio.eof.set(true)
            done.get()!!.invoke()
            queue.finish()
            assertEquals(1, audio.closes.get())
        } finally { queue.cancel() }
    }

    @Test(timeout = 5000)
    fun preparesNextPhraseDuringPlaybackAndKeepsOrder() {
        val secondPrepared = CountDownLatch(1)
        val firstPlaying = CountDownLatch(1)
        val releaseFirst = AtomicReference<(() -> Unit)?>(null)
        val played = Collections.synchronizedList(mutableListOf<String>())
        val handles = ConcurrentHashMap<String, Audio>()
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { text ->
                Audio(text).also { handles[text] = it; if (text == "Вторая!") secondPrepared.countDown() }
            },
            playPrepared = { handle, done ->
                val audio = handle as Audio
                played.add(audio.text)
                if (audio.text == "Первая!") { releaseFirst.set(done); firstPlaying.countDown() } else done()
            })
        try {
            queue.add("Первая! Вторая! Третья!")
            await(firstPlaying)
            await(secondPrepared)
            assertEquals(listOf("Первая!"), played.toList())
            releaseFirst.get()!!.invoke()
            queue.finish()
            assertEquals(listOf("Первая!", "Вторая!", "Третья!"), played.toList())
            assertEquals(3, handles.size)
            handles.values.forEach { assertEquals(1, it.closes.get()) }
        } finally { queue.cancel() }
    }

    @Test(timeout = 5000)
    fun prefetchIsBoundedWhileFirstPhrasePlays() {
        val firstPlaying = CountDownLatch(1)
        val threePrepared = CountDownLatch(3)
        val count = AtomicInteger(0)
        val handles = Collections.synchronizedList(mutableListOf<Audio>())
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { text ->
                Audio(text).also { handles.add(it); count.incrementAndGet(); threePrepared.countDown() }
            },
            playPrepared = { _, _ -> firstPlaying.countDown() })
        try {
            queue.add((1..10).joinToString(" ") { "Фраза $it!" })
            await(firstPlaying)
            await(threePrepared)
            assertEquals(3, count.get())
            queue.cancel()
            queue.finish()
            handles.toList().forEach { await(it.closed); assertEquals(1, it.closes.get()) }
        } finally { queue.cancel() }
    }

    @Test(timeout = 5000)
    fun cancelClosesActiveAndPrefetchedAndLateDoneCannotRestartSpeech() {
        val firstPlaying = CountDownLatch(1)
        val secondPrepared = CountDownLatch(1)
        val done = AtomicReference<(() -> Unit)?>(null)
        val handles = ConcurrentHashMap<String, Audio>()
        val played = Collections.synchronizedList(mutableListOf<String>())
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { text ->
                Audio(text).also { handles[text] = it; if (text == "Вторая!") secondPrepared.countDown() }
            },
            playPrepared = { handle, callback ->
                played.add((handle as Audio).text)
                done.set(callback)
                firstPlaying.countDown()
            })
        try {
            queue.add("Первая! Вторая!")
            await(firstPlaying)
            await(secondPrepared)
            queue.cancel()
            queue.add("Поздняя!")
            done.get()!!.invoke()
            done.get()!!.invoke()
            queue.finish()
            assertEquals(listOf("Первая!"), played.toList())
            handles.values.forEach { await(it.closed); assertEquals(1, it.closes.get()) }
            assertEquals(2, handles.size)
        } finally { queue.cancel() }
    }

    @Test(timeout = 5000)
    fun latePreparedHandleAfterCancelIsClosedWithoutPlayback() {
        val preparing = CountDownLatch(1)
        val release = CountDownLatch(1)
        val audio = Audio("Поздняя!")
        val played = AtomicInteger(0)
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { preparing.countDown(); awaitDespiteInterrupt(release); audio },
            playPrepared = { _, done -> played.incrementAndGet(); done() })
        try {
            queue.add("Поздняя!")
            await(preparing)
            queue.cancel()
            queue.finish()
            assertEquals(0, played.get())
            release.countDown()
            await(audio.closed)
            assertEquals(1, audio.closes.get())
            assertEquals(0, played.get())
        } finally { release.countDown(); queue.cancel() }
    }

    @Test(timeout = 5000)
    fun shouldStopClosesActiveAndPrefetchedHandles() {
        val stop = AtomicBoolean(false)
        val firstPlaying = CountDownLatch(1)
        val secondPrepared = CountDownLatch(1)
        val handles = ConcurrentHashMap<String, Audio>()
        val played = Collections.synchronizedList(mutableListOf<String>())
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { stop.get() },
            prepare = { text -> Audio(text).also { handles[text] = it; if (text == "Вторая!") secondPrepared.countDown() } },
            playPrepared = { handle, _ -> played.add((handle as Audio).text); firstPlaying.countDown() })
        try {
            queue.add("Первая! Вторая!")
            await(firstPlaying)
            await(secondPrepared)
            stop.set(true)
            queue.finish()
            handles.values.forEach { await(it.closed); assertEquals(1, it.closes.get()) }
            assertEquals(listOf("Первая!"), played.toList())
        } finally { queue.cancel() }
    }

    @Test(timeout = 5000)
    fun playbackDeadlineClosesActiveAndPrefetchedHandles() {
        val firstPlaying = CountDownLatch(1)
        val secondPrepared = CountDownLatch(1)
        val handles = ConcurrentHashMap<String, Audio>()
        val played = Collections.synchronizedList(mutableListOf<String>())
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { text ->
                Audio(text).also {
                    handles[text] = it
                    if (text == "Вторая!") secondPrepared.countDown() else await(secondPrepared)
                }
            },
            playPrepared = { handle, _ -> played.add((handle as Audio).text); firstPlaying.countDown() },
            playbackTimeoutMs = 200)
        try {
            queue.add("Первая! Вторая!")
            await(firstPlaying)
            await(secondPrepared)
            assertEquals(setOf("Первая!", "Вторая!"), handles.keys.toSet())
            queue.finish()
            handles.values.forEach { await(it.closed); assertEquals(1, it.closes.get()) }
            assertEquals(listOf("Первая!"), played.toList())
        } finally { queue.cancel() }
    }

    @Test(timeout = 5000)
    fun preparationDeadlineClosesLateHandleAndKeepsNextPhrase() {
        val preparing = CountDownLatch(1)
        val release = CountDownLatch(1)
        val late = Audio("Первая!")
        val next = Audio("Вторая!")
        val played = Collections.synchronizedList(mutableListOf<String>())
        val queue = NativeSpeechQueue({ _, _ -> fail("prepared audio must be used") }, { false },
            prepare = { text ->
                if (text == "Первая!") { preparing.countDown(); awaitDespiteInterrupt(release); late } else next
            },
            playPrepared = { handle, done -> played.add((handle as Audio).text); done() },
            preparationTimeoutMs = 200)
        try {
            queue.add("Первая! Вторая!")
            await(preparing)
            queue.finish()
            assertEquals(listOf("Вторая!"), played.toList())
            assertEquals(1, next.closes.get())
            release.countDown()
            await(late.closed)
            assertEquals(1, late.closes.get())
        } finally { release.countDown(); queue.cancel() }
    }

    @Test(timeout = 5000)
    fun firstPhraseDoesNotWaitForCompleteReplyAndKeepsDecimals() {
        val heard = Collections.synchronizedList(mutableListOf<String>())
        val first = CountDownLatch(1)
        val queue = NativeSpeechQueue({ text, done -> heard.add(text); first.countDown(); done() }, { false })
        try {
            queue.add("[emo:")
            queue.add("joy] Привет!")
            await(first)
            assertEquals(listOf("Привет!"), heard.toList())
            queue.add(" Число 3.")
            queue.add("14. Последняя часть")
            queue.finish()
            assertEquals(listOf("Привет!", "Число 3.14.", "Последняя часть"), heard.toList())
        } finally { queue.cancel() }
    }

    @Test(timeout = 5000)
    fun interruptionNeverStartsQueuedSpeech() {
        val interrupted = AtomicBoolean(false)
        val first = CountDownLatch(1)
        val heard = Collections.synchronizedList(mutableListOf<String>())
        val queue = NativeSpeechQueue({ text, _ -> heard.add(text); first.countDown() }, { interrupted.get() })
        try {
            queue.add("Первая! Следующая! Последняя!")
            await(first)
            interrupted.set(true)
            queue.finish()
            assertEquals(listOf("Первая!"), heard.toList())
        } finally { queue.cancel() }
    }
}
