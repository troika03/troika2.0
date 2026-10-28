package com.troika.hermes_assistant

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.*
import org.junit.Test

class AccountSessionRefreshTest {
    private data class Identity(val origin: String = "https://first.test", val owner: String = "first", val session: String = "ses_first", val generation: Long = 1)
    private val identity = Identity()
    private val initial = AccountSessionRefresh.State(identity, "trk_live_old", "trk_refresh_old", 1L)
    private val tokens = AccountSessionRefresh.Tokens("trk_live_new", "trk_refresh_new", 900_000L, "ses_first")

    private class Store(initial: AccountSessionRefresh.State<Identity>?) : AccountSessionRefresh.Store<Identity> {
        var value = initial
        var rejects = 0
        var saves = 0
        var storageAvailable = true
        @Synchronized override fun read() = value
        @Synchronized fun replace(state: AccountSessionRefresh.State<Identity>?) { value = state }
        @Synchronized override fun publish(expected: AccountSessionRefresh.State<Identity>, tokens: AccountSessionRefresh.Tokens): Boolean {
            if (!storageAvailable || value != expected) return false
            value = expected.copy(accessToken = tokens.accessToken, refreshToken = tokens.refreshToken, expiresAtMillis = tokens.expiresAtMillis)
            saves++
            return true
        }
        @Synchronized override fun reject(expected: AccountSessionRefresh.State<Identity>) {
            if (value == expected) { rejects++; value = null }
        }
    }

    private fun await(latch: CountDownLatch) = assertTrue(latch.await(2, TimeUnit.SECONDS))

    @Test(timeout = 5000) fun parallelExpiredCallersConsumeOneRefreshCredential() {
        val store = Store(initial)
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val requests = AtomicInteger()
        val service = AccountSessionRefresh(store, {
            requests.incrementAndGet(); started.countDown(); await(release)
            AccountSessionRefresh.Result.Success(tokens)
        }, { 100L })
        val first = AtomicReference<String>()
        val second = AtomicReference<String>()
        val a = Thread { first.set(service.accessToken(identity)) }.apply { start() }
        await(started)
        val b = Thread { second.set(service.accessToken(identity)) }.apply { start() }
        release.countDown(); a.join(2000); b.join(2000)
        assertEquals("trk_live_new", first.get()); assertEquals(first.get(), second.get())
        assertEquals(1, requests.get()); assertEquals(1, store.saves)
    }

    @Test(timeout = 5000) fun logoutDoesNotWaitForNetworkAndLateSuccessCannotRestoreSession() {
        val store = Store(initial)
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val result = AtomicReference<String>()
        val service = AccountSessionRefresh(store, {
            started.countDown(); await(release); AccountSessionRefresh.Result.Success(tokens)
        }, { 100L })
        val worker = Thread { result.set(service.accessToken(identity)) }.apply { start() }
        await(started)
        val loggedOut = CountDownLatch(1)
        Thread { store.replace(null); loggedOut.countDown() }.start()
        await(loggedOut)
        release.countDown(); worker.join(2000)
        assertEquals("", result.get()); assertNull(store.read()); assertEquals(0, store.saves)
    }

    @Test fun replacedOriginOwnerSessionOrGenerationRejectsLateRefresh() {
        for (next in listOf(identity.copy(origin = "https://next.test"), identity.copy(owner = "next"),
            identity.copy(session = "ses_next"), identity.copy(generation = 2))) {
            val store = Store(initial)
            val replacement = initial.copy(identity = next, accessToken = "trk_live_other", refreshToken = "trk_refresh_other")
            val service = AccountSessionRefresh(store, {
                store.replace(replacement); AccountSessionRefresh.Result.Success(tokens)
            }, { 100L })
            assertEquals("", service.accessToken(identity)); assertEquals(replacement, store.read())
            assertEquals(0, store.saves)
        }
    }

    @Test fun lateUnauthorizedResponseDoesNotRevokeReplacement() {
        val store = Store(initial)
        val replacement = initial.copy(identity = identity.copy(generation = 2))
        val service = AccountSessionRefresh(store, {
            store.replace(replacement); AccountSessionRefresh.Result.Rejected
        }, { 100L })
        assertEquals("", service.accessToken(identity)); assertEquals(replacement, store.read()); assertEquals(0, store.rejects)
    }

    @Test fun rejectedCurrentRefreshInvalidatesOnlyItsSession() {
        val store = Store(initial)
        val service = AccountSessionRefresh(store, { AccountSessionRefresh.Result.Rejected }, { 100L })
        assertEquals("", service.accessToken(identity)); assertNull(store.read()); assertEquals(1, store.rejects)
    }

    @Test fun temporaryFailureOrStorageFailurePreservesPreviousCredentials() {
        for (networkFailure in listOf(true, false)) {
            val store = Store(initial).apply { storageAvailable = networkFailure }
            val service = AccountSessionRefresh(store, {
                if (networkFailure) AccountSessionRefresh.Result.Unavailable else AccountSessionRefresh.Result.Success(tokens)
            }, { 100L })
            assertEquals("", service.accessToken(identity)); assertEquals(initial, store.read())
            assertEquals(0, store.rejects); assertEquals(0, store.saves)
        }
    }

    @Test fun forcedRetryReusesTokenAlreadyRotatedByAnotherCaller() {
        val store = Store(initial)
        var requests = 0
        val service = AccountSessionRefresh(store, { requests++; AccountSessionRefresh.Result.Success(tokens) }, { 100L })
        assertEquals("trk_live_new", service.accessToken(identity, force = true, rejectedToken = "trk_live_old"))
        assertEquals("trk_live_new", service.accessToken(identity, force = true, rejectedToken = "trk_live_old"))
        assertEquals(1, requests)
    }

    @Test fun freshAccountAndLocalGatewayDoNotSendRefreshRequests() {
        for (state in listOf(initial.copy(expiresAtMillis = 900_000L), initial.copy(accessToken = "local_gateway"))) {
            val service = AccountSessionRefresh(Store(state), { fail("unexpected refresh"); AccountSessionRefresh.Result.Unavailable }, { 100L })
            assertEquals(state.accessToken, service.accessToken(identity))
        }
    }

    @Test fun legacyUpgradeHasNoRefreshCredentialAndStillPublishesPair() {
        val store = Store(initial.copy(refreshToken = ""))
        val service = AccountSessionRefresh(store, { state ->
            assertEquals("", state.refreshToken); assertEquals("trk_live_old", state.accessToken)
            AccountSessionRefresh.Result.Success(tokens)
        }, { 100L })
        assertEquals("trk_live_new", service.accessToken(identity)); assertEquals("trk_refresh_new", store.read()?.refreshToken)
    }
}
