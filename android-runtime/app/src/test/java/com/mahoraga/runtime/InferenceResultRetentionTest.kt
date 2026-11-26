package com.mahoraga.runtime

import java.util.concurrent.atomic.AtomicLong
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InferenceResultRetentionTest {
    @Test
    fun repeatedReadsReturnTheSameResultUntilAcknowledged() {
        val clock = AtomicLong(1_000L)
        val retention = InferenceResultRetention(
            ttlNanos = 100L,
            nowNanos = { clock.get() },
        )
        val result = RetainedInferenceResult(
            status = "completed",
            text = "resposta",
            elapsedSeconds = 1.25,
            deadlineMet = true,
            taskClass = "interactive",
        )

        assertTrue(retention.retain("request-1", result))
        assertEquals(result, retention.get("request-1"))
        assertEquals(result, retention.get("request-1"))
        assertEquals(
            InferenceResultRetention.AckStatus.ACKNOWLEDGED,
            retention.acknowledge("request-1"),
        )
        assertNull(retention.get("request-1"))
        assertTrue(retention.isKnown("request-1"))
        assertEquals(
            InferenceResultRetention.AckStatus.ALREADY_ACKNOWLEDGED,
            retention.acknowledge("request-1"),
        )
    }

    @Test
    fun unacknowledgedResultsExpireAfterTtl() {
        val clock = AtomicLong(10L)
        val retention = InferenceResultRetention(
            ttlNanos = 50L,
            nowNanos = { clock.get() },
        )
        assertTrue(
            retention.retain(
                "request-expiring",
                RetainedInferenceResult(status = "failed", error = "fixture"),
            )
        )

        clock.addAndGet(49L)
        assertTrue(retention.isKnown("request-expiring"))
        clock.incrementAndGet()
        assertFalse(retention.isKnown("request-expiring"))
        assertEquals(0, retention.retainedCount())
    }

    @Test
    fun acknowledgedRequestIdRemainsReservedUntilTtl() {
        val clock = AtomicLong(100L)
        val retention = InferenceResultRetention(
            ttlNanos = 25L,
            nowNanos = { clock.get() },
        )
        assertTrue(
            retention.retain(
                "request-reserved",
                RetainedInferenceResult(status = "completed", text = "ok"),
            )
        )
        assertEquals(
            InferenceResultRetention.AckStatus.ACKNOWLEDGED,
            retention.acknowledge("request-reserved"),
        )
        assertFalse(
            retention.retain(
                "request-reserved",
                RetainedInferenceResult(status = "completed", text = "duplicate"),
            )
        )
        clock.addAndGet(25L)
        assertFalse(retention.isKnown("request-reserved"))
        assertTrue(
            retention.retain(
                "request-reserved",
                RetainedInferenceResult(status = "completed", text = "new-window"),
            )
        )
    }

    @Test
    fun retainedResultCountIsBounded() {
        val retention = InferenceResultRetention(maxEntries = 1)
        assertTrue(
            retention.retain(
                "first",
                RetainedInferenceResult(status = "completed", text = "one"),
            )
        )
        assertFalse(
            retention.retain(
                "second",
                RetainedInferenceResult(status = "completed", text = "two"),
            )
        )
        assertEquals(1, retention.retainedCount())
    }

    @Test
    fun acknowledgementLedgerCapacityNeverDropsUnacknowledgedResult() {
        val retention = InferenceResultRetention(maxAcknowledgements = 1)
        assertTrue(
            retention.retain(
                "first",
                RetainedInferenceResult(status = "completed", text = "one"),
            )
        )
        assertEquals(
            InferenceResultRetention.AckStatus.ACKNOWLEDGED,
            retention.acknowledge("first"),
        )
        assertTrue(
            retention.retain(
                "second",
                RetainedInferenceResult(status = "completed", text = "two"),
            )
        )
        assertEquals(
            InferenceResultRetention.AckStatus.CAPACITY,
            retention.acknowledge("second"),
        )
        assertEquals("two", retention.get("second")?.text)
    }

}
