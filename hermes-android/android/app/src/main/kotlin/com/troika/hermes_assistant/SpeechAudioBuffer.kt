package com.troika.hermes_assistant

import java.io.IOException
import java.io.InterruptedIOException

/** One bounded, replayable RAM stream. EOF is visible only after normal completion. */
internal class SpeechAudioBuffer(private val limit: Int = 10 * 1024 * 1024) : AutoCloseable {
    private val lock = Object()
    private val blocks = ArrayList<ByteArray>()
    private var size = 0
    private var complete = false
    private var closed = false
    private var failure: IOException? = null

    fun append(bytes: ByteArray, count: Int) = synchronized(lock) {
        check(count in 0..bytes.size)
        if (closed) throw IOException("Speech cancelled")
        failure?.let { throw it }
        if (complete) throw IOException("Speech already complete")
        if (count > limit - size) {
            val error = IOException("Speech response exceeds RAM limit")
            failure = error
            lock.notifyAll()
            throw error
        }
        if (count > 0) {
            blocks.add(bytes.copyOf(count))
            size += count
            lock.notifyAll()
        }
    }

    fun finish() = synchronized(lock) {
        if (!closed && failure == null) complete = true
        lock.notifyAll()
    }

    fun fail(error: IOException) = synchronized(lock) {
        if (!closed && !complete && failure == null) failure = error
        lock.notifyAll()
    }

    fun wakeReaders() = synchronized(lock) { lock.notifyAll() }

    fun readAt(position: Long, target: ByteArray, offset: Int, length: Int,
               cancelled: () -> Boolean = { false }): Int = synchronized(lock) {
        require(position >= 0 && offset >= 0 && length >= 0 && offset <= target.size - length)
        if (length == 0) return@synchronized 0
        while (true) {
            if (closed || cancelled()) throw IOException("Speech cancelled")
            failure?.let { throw it }
            if (position < size) break
            if (complete) return@synchronized -1
            try { lock.wait(100) } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
                throw InterruptedIOException("Speech read interrupted")
            }
        }
        var start = 0L
        for (block in blocks) {
            if (position < start + block.size) {
                val within = (position - start).toInt()
                val count = minOf(length, block.size - within)
                System.arraycopy(block, within, target, offset, count)
                return@synchronized count
            }
            start += block.size
        }
        throw IOException("Invalid speech buffer position")
    }

    override fun close() = synchronized(lock) {
        closed = true
        blocks.forEach { it.fill(0) }
        blocks.clear()
        size = 0
        lock.notifyAll()
    }
}
