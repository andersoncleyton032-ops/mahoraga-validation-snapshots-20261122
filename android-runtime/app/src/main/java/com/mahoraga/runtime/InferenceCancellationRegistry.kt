package com.mahoraga.runtime

/**
 * Request-scoped cancellation state.
 *
 * All transitions are synchronized so cancellation and terminal completion
 * have a single winner. A queued request can be marked before its executor
 * task starts; an active request can be interrupted by its owner. Terminal
 * requests reject late cancellation.
 */
internal class InferenceCancellationRegistry {
    enum class CancelResult {
        REQUESTED,
        ALREADY_REQUESTED,
        ALREADY_COMPLETED,
        UNKNOWN,
    }

    private enum class State { QUEUED, ACTIVE, TERMINAL }

    private data class Request(
        var state: State = State.QUEUED,
        var cancellationRequested: Boolean = false,
    )

    private val requests = mutableMapOf<String, Request>()

    @Synchronized
    fun register(requestId: String): Boolean {
        if (requestId.isBlank() || requests.containsKey(requestId)) return false
        requests[requestId] = Request()
        return true
    }

    /** Returns false when cancellation was requested before executor admission. */
    @Synchronized
    fun begin(requestId: String): Boolean {
        val request = requests[requestId] ?: return false
        if (request.state != State.QUEUED) return false
        if (request.cancellationRequested) {
            request.state = State.TERMINAL
            return false
        }
        request.state = State.ACTIVE
        return true
    }

    @Synchronized
    fun requestCancellation(requestId: String): CancelResult {
        val request = requests[requestId] ?: return CancelResult.UNKNOWN
        if (request.state == State.TERMINAL) return CancelResult.ALREADY_COMPLETED
        if (request.cancellationRequested) return CancelResult.ALREADY_REQUESTED
        request.cancellationRequested = true
        return CancelResult.REQUESTED
    }

    @Synchronized
    fun isCancellationRequested(requestId: String): Boolean =
        requests[requestId]?.cancellationRequested == true

    /** Marks terminal; safe from both the callable and FutureTask completion hook. */
    @Synchronized
    fun finish(requestId: String): Boolean {
        val request = requests[requestId] ?: return false
        request.state = State.TERMINAL
        return request.cancellationRequested
    }

    @Synchronized
    fun forget(requestId: String) {
        requests.remove(requestId)
    }
}
