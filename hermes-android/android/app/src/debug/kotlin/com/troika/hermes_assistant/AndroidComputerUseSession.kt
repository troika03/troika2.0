package com.troika.hermes_assistant

import java.util.UUID

/** Local grant for one disposable editor. Calls to Android run outside the session lock. */
internal class AndroidComputerUseSession(private val now: () -> Long, private val editor: Editor) {
    interface Editor {
        fun inspect(): EditorState?
        fun write(windowId: Int, text: String): Boolean
        fun verify(windowId: Int, text: String): Boolean
    }

    data class EditorState(val windowId: Int, val empty: Boolean)
    data class Observation(val id: UUID, val canWrite: Boolean)
    enum class Status { INSPECTED, VERIFIED, STOPPED, BUSY, DUPLICATE, STALE, INVALID_TEXT, TARGET_UNAVAILABLE }
    data class Result(val status: Status, val observation: Observation? = null)

    private data class Snapshot(val observation: Observation, val windowId: Int, val expiresAt: Long)
    private data class Permit(val text: String, val expiresAt: Long)

    private var deadline: Long? = null
    private var closed = false
    private var inFlight = false
    private val requests = mutableSetOf<UUID>()
    private var snapshot: Snapshot? = null
    private var permit: Permit? = null
    private var applied = false

    @Synchronized
    fun allow(): Boolean {
        if (deadline != null || closed) return false
        deadline = now() + 120_000
        return true
    }

    @Synchronized
    fun stop() {
        closed = true
        snapshot = null
        permit = null
    }

    fun inspect(requestId: UUID): Result = runCommand(requestId) {
        val target = editor.inspect()
        synchronized(this) {
            if (!active()) return@synchronized Result(Status.STOPPED)
            if (target == null) {
                stop()
                return@synchronized Result(Status.TARGET_UNAVAILABLE)
            }
            val observed = Observation(UUID.randomUUID(), target.empty)
            snapshot = Snapshot(observed, target.windowId, now() + 15_000)
            Result(Status.INSPECTED, observed)
        }
    }

    fun write(requestId: UUID, observationId: UUID, text: String): Result = runCommand(requestId) {
        if (text.isEmpty() || text.length > 512 || text.any(Char::isISOControl) ||
            !Charsets.UTF_8.newEncoder().canEncode(text)
        ) return@runCommand Result(Status.INVALID_TEXT)
        val observed = synchronized(this) {
            if (!active()) return@runCommand Result(Status.STOPPED)
            val current = snapshot
            if (current == null || current.observation.id != observationId ||
                !current.observation.canWrite || now() >= current.expiresAt
            ) return@runCommand Result(Status.STALE)
            snapshot = null
            permit = Permit(text, current.expiresAt)
            current
        }
        val accepted = editor.write(observed.windowId, text)
        val changed = synchronized(this) { active() && applied }
        val verified = accepted && changed && editor.verify(observed.windowId, text)
        synchronized(this) {
            val status = when {
                !active() -> Status.STOPPED
                verified -> Status.VERIFIED
                now() >= observed.expiresAt && !applied -> Status.STALE
                else -> Status.TARGET_UNAVAILABLE
            }
            permit = null
            if (status != Status.STALE) stop()
            Result(status)
        }
    }

    /** Invoked on the editor's UI thread immediately before the actual mutation. */
    @Synchronized
    fun applyWrite(text: String, apply: () -> Boolean): Boolean {
        val allowed = permit ?: return false
        if (!active() || now() >= allowed.expiresAt || allowed.text != text) return false
        permit = null
        applied = apply()
        return applied
    }

    private fun active(): Boolean {
        if (closed) return false
        val end = deadline ?: return false
        if (now() < end) return true
        stop()
        return false
    }

    private fun runCommand(requestId: UUID, execute: () -> Result): Result {
        synchronized(this) {
            if (!active()) return Result(Status.STOPPED)
            if (requestId in requests) return Result(Status.DUPLICATE)
            if (inFlight) return Result(Status.BUSY)
            if (requests.size >= 8) {
                stop()
                return Result(Status.STOPPED)
            }
            requests.add(requestId)
            inFlight = true
        }
        return try {
            execute()
        } catch (_: RuntimeException) {
            stop()
            Result(Status.TARGET_UNAVAILABLE)
        } finally {
            synchronized(this) { inFlight = false }
        }
    }
}
