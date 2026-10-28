package com.troika.hermes_assistant

import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class SpeechAudioBufferTest {
    @Test(timeout = 3000)
    fun readsFirstBytesBeforeEofAndReopensFromRam() {
        val buffer = SpeechAudioBuffer(16)
        try {
            buffer.append(byteArrayOf(1, 2, 3), 3)
            val out = ByteArray(8)
            assertEquals(3, buffer.readAt(0, out, 0, out.size))
            assertArrayEquals(byteArrayOf(1, 2, 3), out.copyOf(3))
            buffer.append(byteArrayOf(4, 5), 2)
            assertEquals(2, buffer.readAt(3, out, 0, out.size))
            assertArrayEquals(byteArrayOf(4, 5), out.copyOf(2))
            assertEquals(3, buffer.readAt(0, out, 0, out.size))
            buffer.finish()
            assertEquals(-1, buffer.readAt(5, out, 0, out.size))
        } finally { buffer.close() }
    }

    @Test(timeout = 3000)
    fun emptyReadWaitsForProducerInsteadOfInventingEof() {
        val buffer = SpeechAudioBuffer(8)
        val executor = Executors.newSingleThreadExecutor()
        val entered = CountDownLatch(1)
        try {
            val read = executor.submit<Int> { entered.countDown(); buffer.readAt(0, ByteArray(8), 0, 8) }
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            assertFalse(read.isDone)
            buffer.append(byteArrayOf(9), 1)
            assertEquals(1, read.get(1, TimeUnit.SECONDS).toInt())
        } finally { buffer.close(); executor.shutdownNow() }
    }

    @Test(timeout = 3000)
    fun closeWakesReaderAndRejectsReplay() {
        val buffer = SpeechAudioBuffer(8)
        val executor = Executors.newSingleThreadExecutor()
        val entered = CountDownLatch(1)
        try {
            buffer.append(byteArrayOf(1), 1)
            val read = executor.submit<Boolean> {
                entered.countDown()
                try { buffer.readAt(1, ByteArray(8), 0, 8); false } catch (_: IOException) { true }
            }
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            buffer.close()
            assertTrue(read.get(1, TimeUnit.SECONDS))
            try { buffer.readAt(0, ByteArray(8), 0, 8); fail("Closed bytes must not replay") } catch (_: IOException) {}
        } finally { buffer.close(); executor.shutdownNow() }
    }

    @Test(timeout = 3000)
    fun failedOrOversizedDownloadNeverBecomesNormalEof() {
        val failed = SpeechAudioBuffer(8)
        val bounded = SpeechAudioBuffer(2)
        try {
            failed.append(byteArrayOf(1), 1)
            failed.fail(IOException("Synthetic failure"))
            failed.finish()
            try { failed.readAt(0, ByteArray(8), 0, 8); fail("Failure must propagate") } catch (_: IOException) {}
            bounded.append(byteArrayOf(1, 2), 2)
            try { bounded.append(byteArrayOf(3), 1); fail("RAM limit must be enforced") } catch (_: IOException) {}
            bounded.finish()
            try { bounded.readAt(0, ByteArray(8), 0, 8); fail("Oversize must fail playback") } catch (_: IOException) {}
        } finally { failed.close(); bounded.close() }
    }
}
