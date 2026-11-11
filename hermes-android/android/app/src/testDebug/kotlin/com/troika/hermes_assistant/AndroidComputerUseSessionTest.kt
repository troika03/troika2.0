package com.troika.hermes_assistant

import com.troika.hermes_assistant.AndroidComputerUseSession.Status
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class AndroidComputerUseSessionTest {
    private val fixture = Editor()
    private var now = 0L
    private val session = AndroidComputerUseSession({ now }, fixture)

    @Test
    fun inspectionAndWriteRequireConsentAndVerifyActualChange() {
        val request = UUID.randomUUID()
        assertEquals(Status.STOPPED, session.inspect(request).status)
        assertEquals(0, fixture.inspections)
        assertTrue(session.allow())
        assertFalse(session.allow())
        val observation = session.inspect(request).observation!!
        assertTrue(observation.canWrite)
        assertEquals(Status.DUPLICATE, session.inspect(request).status)
        assertEquals(1, fixture.inspections)
        assertEquals(Status.INVALID_TEXT, session.write(UUID.randomUUID(), observation.id, "a\u0000b").status)
        assertEquals(Status.VERIFIED, session.write(UUID.randomUUID(), observation.id, "Проба").status)
        assertEquals("Проба", fixture.contents)
        assertEquals(Status.STOPPED, session.write(UUID.randomUUID(), observation.id, "late").status)
    }

    @Test
    fun stopRevokesAlreadyDispatchedUiActionAndRejectsParallelRequest() {
        session.allow()
        val observation = session.inspect(UUID.randomUUID()).observation!!
        val dispatched = CountDownLatch(1)
        val resume = CountDownLatch(1)
        fixture.beforeApply = {
            dispatched.countDown()
            check(resume.await(3, TimeUnit.SECONDS))
        }
        val worker = Executors.newSingleThreadExecutor()
        try {
            val result = worker.submit<Status> { session.write(UUID.randomUUID(), observation.id, "late").status }
            assertTrue(dispatched.await(3, TimeUnit.SECONDS))
            assertEquals(Status.BUSY, session.inspect(UUID.randomUUID()).status)
            session.stop()
            resume.countDown()
            assertEquals(Status.STOPPED, result.get(3, TimeUnit.SECONDS))
            assertEquals("", fixture.contents)
        } finally {
            resume.countDown()
            worker.shutdownNow()
        }
    }

    @Test
    fun observationExpiresWhileAccessibilityDispatchIsPending() {
        session.allow()
        val first = session.inspect(UUID.randomUUID()).observation!!
        val latest = session.inspect(UUID.randomUUID()).observation!!
        assertEquals(Status.STALE, session.write(UUID.randomUUID(), first.id, "old").status)
        fixture.beforeApply = { now = 15_000 }
        assertEquals(Status.STALE, session.write(UUID.randomUUID(), latest.id, "late").status)
        assertEquals("", fixture.contents)
        now = 120_000
        assertEquals(Status.STOPPED, session.inspect(UUID.randomUUID()).status)
    }

    @Test
    fun changedWindowAndUnverifiedTextCannotReturnSuccess() {
        session.allow()
        val observation = session.inspect(UUID.randomUUID()).observation!!
        fixture.windowId++
        assertEquals(Status.TARGET_UNAVAILABLE, session.write(UUID.randomUUID(), observation.id, "wrong").status)
        assertEquals("", fixture.contents)
        val retry = AndroidComputerUseSession({ now }, fixture)
        retry.allow()
        fixture.sessionForCallback = { retry }
        val next = retry.inspect(UUID.randomUUID()).observation!!
        fixture.readbackAvailable = false
        assertEquals(Status.TARGET_UNAVAILABLE, retry.write(UUID.randomUUID(), next.id, "unverified").status)
        assertEquals("unverified", fixture.contents)
    }

    private inner class Editor : AndroidComputerUseSession.Editor {
        var contents = ""
        var windowId = 7
        var inspections = 0
        var readbackAvailable = true
        var beforeApply: () -> Unit = {}

        override fun inspect(): AndroidComputerUseSession.EditorState {
            inspections++
            return AndroidComputerUseSession.EditorState(windowId, contents.isEmpty())
        }

        override fun write(windowId: Int, text: String): Boolean {
            beforeApply()
            return windowId == this.windowId && sessionForCallback().applyWrite(text) {
                contents = text
                true
            }
        }

        override fun verify(windowId: Int, text: String): Boolean =
            readbackAvailable && windowId == this.windowId && contents == text

        var sessionForCallback: () -> AndroidComputerUseSession = { session }
    }
}
