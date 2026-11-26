package com.mahoraga.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicReference

class InferenceCancellationRegistryTest {
    @Test
    fun queuedRequestCanBeCancelledBeforeItStarts() {
        val registry = InferenceCancellationRegistry()
        assertTrue(registry.register("queued"))
        assertEquals(
            InferenceCancellationRegistry.CancelResult.REQUESTED,
            registry.requestCancellation("queued"),
        )
        assertFalse(registry.begin("queued"))
        assertTrue(registry.finish("queued"))
        assertEquals(
            InferenceCancellationRegistry.CancelResult.ALREADY_COMPLETED,
            registry.requestCancellation("queued"),
        )
    }

    @Test
    fun activeRequestRecordsCancellationUntilTerminalCompletion() {
        val registry = InferenceCancellationRegistry()
        assertTrue(registry.register("active"))
        assertTrue(registry.begin("active"))
        assertEquals(
            InferenceCancellationRegistry.CancelResult.REQUESTED,
            registry.requestCancellation("active"),
        )
        assertTrue(registry.isCancellationRequested("active"))
        assertTrue(registry.finish("active"))
        assertEquals(
            InferenceCancellationRegistry.CancelResult.ALREADY_COMPLETED,
            registry.requestCancellation("active"),
        )
    }

    @Test
    fun repeatedCancellationIsIdempotent() {
        val registry = InferenceCancellationRegistry()
        assertTrue(registry.register("repeat"))
        assertTrue(registry.begin("repeat"))
        assertEquals(
            InferenceCancellationRegistry.CancelResult.REQUESTED,
            registry.requestCancellation("repeat"),
        )
        assertEquals(
            InferenceCancellationRegistry.CancelResult.ALREADY_REQUESTED,
            registry.requestCancellation("repeat"),
        )
    }

    @Test
    fun unknownAndTerminalRequestsCannotBeCancelled() {
        val registry = InferenceCancellationRegistry()
        assertEquals(
            InferenceCancellationRegistry.CancelResult.UNKNOWN,
            registry.requestCancellation("missing"),
        )
        assertTrue(registry.register("done"))
        assertTrue(registry.begin("done"))
        assertFalse(registry.finish("done"))
        assertEquals(
            InferenceCancellationRegistry.CancelResult.ALREADY_COMPLETED,
            registry.requestCancellation("done"),
        )
    }

    @Test
    fun cancellationIsIsolatedByRequestId() {
        val registry = InferenceCancellationRegistry()
        assertTrue(registry.register("request-a"))
        assertTrue(registry.register("request-b"))
        assertTrue(registry.begin("request-a"))
        assertTrue(registry.begin("request-b"))

        assertEquals(
            InferenceCancellationRegistry.CancelResult.REQUESTED,
            registry.requestCancellation("request-a"),
        )
        assertTrue(registry.isCancellationRequested("request-a"))
        assertFalse(registry.isCancellationRequested("request-b"))
        assertTrue(registry.finish("request-a"))
        assertFalse(registry.finish("request-b"))
    }

    @Test
    fun concurrentCancellationAndCompletionHaveOneConsistentWinner() {
        repeat(100) { index ->
            val registry = InferenceCancellationRegistry()
            val requestId = "race-$index"
            assertTrue(registry.register(requestId))
            assertTrue(registry.begin(requestId))
            val start = CountDownLatch(1)
            val cancelResult = AtomicReference<InferenceCancellationRegistry.CancelResult>()
            val completionResult = AtomicReference<Boolean>()

            val cancelThread = Thread {
                start.await()
                cancelResult.set(registry.requestCancellation(requestId))
            }
            val completionThread = Thread {
                start.await()
                completionResult.set(registry.finish(requestId))
            }
            cancelThread.start()
            completionThread.start()
            start.countDown()
            cancelThread.join()
            completionThread.join()

            val cancellationWon = cancelResult.get() ==
                InferenceCancellationRegistry.CancelResult.REQUESTED
            if (cancellationWon) {
                assertTrue(completionResult.get())
            } else {
                assertEquals(
                    InferenceCancellationRegistry.CancelResult.ALREADY_COMPLETED,
                    cancelResult.get(),
                )
                assertFalse(completionResult.get())
            }
        }
    }

    @Test
    fun completionWinsWhenItIsCommittedBeforeCancellation() {
        val registry = InferenceCancellationRegistry()
        assertTrue(registry.register("race"))
        assertTrue(registry.begin("race"))
        assertFalse(registry.finish("race"))
        assertEquals(
            InferenceCancellationRegistry.CancelResult.ALREADY_COMPLETED,
            registry.requestCancellation("race"),
        )
    }
}
