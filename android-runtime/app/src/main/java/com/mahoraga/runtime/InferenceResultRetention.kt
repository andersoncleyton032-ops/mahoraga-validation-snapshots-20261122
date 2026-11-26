package com.mahoraga.runtime

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

internal data class RetainedInferenceResult(
    val status: String,
    val text: String? = null,
    val elapsedSeconds: Double? = null,
    val deadlineMet: Boolean? = null,
    val taskClass: String? = null,
    val error: String? = null,
)

/**
 * Retry-safe, bounded retention for terminal inference results.
 *
 * Results remain addressable until explicit acknowledgement or TTL expiry.
 * A short-lived acknowledgement tombstone prevents request-ID reuse during
 * the same retention window.
 */
internal class InferenceResultRetention(
    private val ttlNanos: Long = TimeUnit.MINUTES.toNanos(10),
    private val maxEntries: Int = 32,
    private val maxAcknowledgements: Int = 128,
    private val nowNanos: () -> Long = System::nanoTime,
) {
    enum class AckStatus { ACKNOWLEDGED, ALREADY_ACKNOWLEDGED, UNKNOWN, CAPACITY }

    private data class Entry(
        val result: RetainedInferenceResult,
        val storedAtNanos: Long,
    )

    private val results = ConcurrentHashMap<String, Entry>()
    private val acknowledgements = ConcurrentHashMap<String, Long>()

    init {
        require(ttlNanos > 0) { "ttlNanos must be positive" }
        require(maxEntries > 0) { "maxEntries must be positive" }
        require(maxAcknowledgements > 0) { "maxAcknowledgements must be positive" }
    }

    fun retain(requestId: String, result: RetainedInferenceResult): Boolean {
        require(requestId.isNotBlank()) { "request_id_required" }
        pruneExpired()
        if (acknowledgements.containsKey(requestId)) return false
        if (results.containsKey(requestId)) return false
        if (results.size >= maxEntries) return false
        return results.putIfAbsent(requestId, Entry(result, nowNanos())) == null
    }

    fun get(requestId: String): RetainedInferenceResult? {
        pruneExpired()
        return results[requestId]?.result
    }

    fun acknowledge(requestId: String): AckStatus {
        pruneExpired()
        if (results.containsKey(requestId) && acknowledgements.size >= maxAcknowledgements) {
            return AckStatus.CAPACITY
        }
        val removed = results.remove(requestId)
        if (removed != null) {
            acknowledgements[requestId] = nowNanos()
            return AckStatus.ACKNOWLEDGED
        }
        return if (acknowledgements.containsKey(requestId)) {
            AckStatus.ALREADY_ACKNOWLEDGED
        } else {
            AckStatus.UNKNOWN
        }
    }

    fun isKnown(requestId: String): Boolean {
        pruneExpired()
        return results.containsKey(requestId) || acknowledgements.containsKey(requestId)
    }

    fun retainedCount(): Int {
        pruneExpired()
        return results.size
    }

    fun pruneExpired() {
        val now = nowNanos()
        results.entries.removeIf { now - it.value.storedAtNanos >= ttlNanos }
        acknowledgements.entries.removeIf { now - it.value >= ttlNanos }
    }
}
