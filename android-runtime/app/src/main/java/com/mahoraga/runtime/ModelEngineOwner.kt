package com.mahoraga.runtime

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.app.ActivityManager
import android.os.BatteryManager
import android.os.PowerManager
import android.os.StatFs
import android.os.Bundle
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.Message
import com.google.ai.edge.litertlm.ThinkingConfig
import com.google.ai.edge.litertlm.SamplerConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.FutureTask
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout

/**
 * Application-scoped LiteRT-LM owner.
 *
 * One executor owns Engine/Conversation creation, streaming and close. The sole
 * cross-thread Conversation operation is cancelProcess(), invoked only after a
 * request-ID match so an active stream can be interrupted immediately. Calls from
 * Termux are asynchronous and request-addressable; polling never duplicates work.
 */
class ModelEngineOwner(context: Context) {
    private val appContext = context.applicationContext
    private val executor: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "mahoraga-litert-owner").apply { isDaemon = true }
    }
    private val inferenceJobs = ConcurrentHashMap<String, Future<InferenceOutcome>>()
    private val inferenceSubmittedAt = ConcurrentHashMap<String, Long>()
    private val resultRetention = InferenceResultRetention()
    private val cancellationRegistry = InferenceCancellationRegistry()
    private val inferenceAdmissionLock = Any()
    private val memoryPressureRequested = AtomicBoolean(false)
    private val requestRetentionTtlNanos = TimeUnit.MINUTES.toNanos(10)

    @Volatile private var loaded = false
    @Volatile private var currentModelPath: String? = null
    @Volatile private var currentBackendName: String? = null
    @Volatile private var lifecycleStatus = "unloaded"

    private data class InferenceOutcome(
        val text: String,
        val elapsedSeconds: Double,
        val deadlineMet: Boolean,
        val taskClass: String,
        val status: String = "completed",
    )

    // Accessed only from the owner executor.
    private var engine: Engine? = null
    @Volatile private var conversation: com.google.ai.edge.litertlm.Conversation? = null
    @Volatile private var activeRequestId: String? = null

    fun status(): Bundle = Bundle().apply {
        pruneExpiredRequests()
        putBoolean("loaded", loaded)
        putBoolean("companion_app_foreground", isAppForeground())
        putBoolean("screen_interactive", isScreenInteractive())
        putBoolean("background_schedule_enabled", isBackgroundScheduleAuthorized())
        putBoolean("gpu_backend_enabled", false)
        putString("model_path", currentModelPath)
        putString("backend_name", currentBackendName)
        putString("lifecycle_status", lifecycleStatus)
        putInt("pending_inferences", inferenceJobs.size)
        putInt("retained_inference_results", resultRetention.retainedCount())
        putLong("available_ram_mb", availableRamMb())
        putInt("thermal_status", thermalStatus())
        batteryPercent()?.let { putInt("battery_percent", it) }
    }

    fun load(
        modelPath: String,
        backendName: String,
        expectedSha256: String
    ): Future<String> = executor.submit<String> {
        val file = File(modelPath).canonicalFile
        require(file.isFile && file.extension.equals("litertlm", ignoreCase = true)) {
            "model_file_invalid"
        }
        val normalizedBackend = backendName.trim().lowercase().ifBlank { "cpu" }
        if (!ModelRuntimeAdmissionPolicy.isBackendAllowed(normalizedBackend)) {
            lifecycleStatus = "load_denied:backend_not_authorized"
            throw IllegalArgumentException("backend_not_authorized")
        }
        if (!ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = isBackgroundScheduleAuthorized(),
                screenInteractive = isScreenInteractive(),
                charging = isCharging()
            )
        ) {
            lifecycleStatus = "load_denied:background_load_not_authorized"
            throw IllegalStateException("model_load_denied:background_load_not_authorized")
        }
        if (thermalStatus() >= PowerManager.THERMAL_STATUS_SEVERE) {
            lifecycleStatus = "load_denied:thermal_state_blocks_model_load"
            throw IllegalStateException("model_load_denied:thermal_state_blocks_model_load")
        }
        val integrity = ModelArtifactIntegrity.verify(file, expectedSha256)
        if (!integrity.trusted) {
            val reason = integrity.reason ?: "model_sha256_mismatch"
            if (!loaded) lifecycleStatus = "load_denied:" + reason
            throw IllegalStateException("model_load_denied:" + reason)
        }
        if (loaded && currentModelPath == file.absolutePath &&
            currentBackendName == normalizedBackend
        ) {
            return@submit "already_loaded"
        }
        unloadOwned()

        val admission = evaluateLoad(file, normalizedBackend)
        if (!admission.first) {
            lifecycleStatus = "load_denied:" + admission.second
            throw IllegalStateException("model_load_denied:" + admission.second)
        }
        lifecycleStatus = "loading"
        val candidate = Engine(
            EngineConfig(
                modelPath = file.absolutePath,
                backend = Backend.CPU(),
                cacheDir = appContext.cacheDir.absolutePath,
            )
        )

        // If initialize throws, do not call close on this uninitialized Engine.
        try {
            candidate.initialize()
        } catch (failure: Throwable) {
            lifecycleStatus = "load_failed"
            throw failure
        }
        if (!ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = isBackgroundScheduleAuthorized(),
                screenInteractive = isScreenInteractive(),
                charging = isCharging()
            )
        ) {
            candidate.close()
            lifecycleStatus = "load_cancelled:background_not_authorized"
            throw IllegalStateException("model_load_cancelled:background_not_authorized")
        }
        if (memoryPressureRequested.get()) {
            candidate.close()
            lifecycleStatus = "unloaded"
            memoryPressureRequested.set(false)
            throw IllegalStateException("model_load_cancelled_by_memory_pressure")
        }

        engine = candidate
        conversation = null
        currentModelPath = file.absolutePath
        currentBackendName = normalizedBackend
        loaded = true
        lifecycleStatus = "loaded"
        "loaded"
    }

    fun submitInference(
        requestId: String,
        prompt: String,
        taskClass: String = "interactive",
        requestedDurationSeconds: Double? = null,
        estimatedAdditionalRamMb: Long? = null,
        thinkingTokenBudget: Int? = null,
        maxOutputTokens: Int? = null,
        allowBackground: Boolean = false,
        topK: Int? = null,
        topP: Double? = null,
        temperature: Double? = null,
    ): String {
        require(requestId.isNotBlank() && requestId.length <= 128) { "request_id_invalid" }
        require(prompt.isNotBlank() && prompt.length <= 64_000) { "prompt_invalid" }
        require(taskClass in setOf("interactive", "reasoning", "maintenance", "background")) {
            "task_class_invalid"
        }
        if (taskClass == "background" && !allowBackground) return "background_not_authorized"
        if (allowBackground && taskClass != "background") return "background_permission_scope_invalid"
        if (!ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = allowBackground,
                taskClass = taskClass,
                backgroundScheduleEnabled = isBackgroundScheduleAuthorized(),
                screenInteractive = isScreenInteractive(),
                charging = isCharging()
            )
        ) return "background_not_authorized"
        require(topK == null || topK in 1..256) { "top_k_invalid" }
        require(topP == null || (topP.isFinite() && topP in 0.0..1.0)) { "top_p_invalid" }
        require(temperature == null || (temperature.isFinite() && temperature in 0.0..2.0)) {
            "temperature_invalid"
        }
        val future = object : FutureTask<InferenceOutcome>({
            if (!cancellationRegistry.begin(requestId)) {
                throw RequestCancellationException()
            }
            // Always enforce the Android-side resource/deadline policy.
            // A duration_policy_applied claim from the Termux IPC caller is not trusted.
            val budgetSeconds = ModelBudgetMath.durationSeconds(
                taskClass, requestedDurationSeconds, thermalStatus(),
                PowerManager.THERMAL_STATUS_MODERATE, batteryPercent(), isCharging()
            )
            val activeEngine = engine ?: throw IllegalStateException("model_not_loaded")
            val admission = evaluateInference(taskClass, estimatedAdditionalRamMb, allowBackground)
            if (!admission.first) {
                unloadOwned()
                throw IllegalStateException("inference_denied:" + admission.second)
            }
            val thinkingTokens = ModelBudgetMath.thinkingTokenBudget(
                taskClass, thinkingTokenBudget
            )
            val outputTokens = ModelBudgetMath.maxOutputTokens(taskClass, maxOutputTokens)
            ModelBudgetMath.validateContextBudget(
                prompt.length, thinkingTokens, outputTokens
            )
            val sampling = ModelSamplingDefaults.resolve(topK, topP, temperature)
            val samplerConfig = SamplerConfig(
                topK = sampling.topK,
                topP = sampling.topP,
                temperature = sampling.temperature,
            )
            val parsedPrompt = ModelPromptEnvelope.parse(prompt)
            val initialMessages = parsedPrompt.initialMessages.map { turn ->
                when (turn.role) {
                    "user" -> Message.user(turn.content)
                    "assistant" -> Message.model(turn.content)
                    else -> throw IllegalArgumentException("prompt_envelope_initial_role_invalid")
                }
            }
            val conversationConfig = ConversationConfig(
                systemInstruction = parsedPrompt.systemInstruction?.let { Contents.of(it) },
                initialMessages = initialMessages,
                samplerConfig = samplerConfig,
                automaticToolCalling = false,
                thinkingConfig = ThinkingConfig(
                    enableThinking = thinkingTokens > 0,
                    thinkingTokenBudget = thinkingTokens,
                ),
                // LiteRT-LM maxOutputToken includes both thinking and final answer tokens.
                maxOutputToken = ModelBudgetMath.totalOutputTokenLimit(thinkingTokens, outputTokens),
            )
            if (cancellationRegistry.isCancellationRequested(requestId)) {
                throw RequestCancellationException()
            }
            val activeConversation = activeEngine.createConversation(conversationConfig)
            synchronized(inferenceAdmissionLock) {
                conversation = activeConversation
                activeRequestId = requestId
            }
            val started = System.nanoTime()
            val response = StringBuilder()
            var deadlineMet = true
            var resourceFailure: String? = null
            var cancellationObserved = false
            var chunks = 0
            try {
                if (cancellationRegistry.isCancellationRequested(requestId)) {
                    activeConversation.cancelProcess()
                    throw RequestCancellationException()
                }
                runBlocking {
                    withTimeout((budgetSeconds * 1000.0).toLong().coerceAtLeast(1L)) {
                        activeConversation.sendMessageAsync(parsedPrompt.finalUserMessage).collect { message ->
                            if (cancellationRegistry.isCancellationRequested(requestId)) {
                                throw RequestCancellationException()
                            }
                            response.append(message.toString())
                            chunks += 1
                            if (memoryPressureRequested.get()) {
                                throw ResourceLimitCancellationException("android_memory_pressure")
                            }
                            if (chunks % 8 == 0) {
                                val liveAdmission = evaluateInference(
                                    taskClass, estimatedAdditionalRamMb, allowBackground
                                )
                                if (!liveAdmission.first) {
                                    throw ResourceLimitCancellationException(liveAdmission.second)
                                }
                            }
                        }
                    }
                }
            } catch (failure: ResourceLimitCancellationException) {
                if (cancellationRegistry.isCancellationRequested(requestId)) {
                    cancellationObserved = true
                } else {
                    activeConversation.cancelProcess()
                    resourceFailure = failure.reason
                }
            } catch (_: TimeoutCancellationException) {
                deadlineMet = false
                activeConversation.cancelProcess()
            } catch (failure: Throwable) {
                if (cancellationRegistry.isCancellationRequested(requestId)) {
                    cancellationObserved = true
                } else {
                    throw failure
                }
            } finally {
                synchronized(inferenceAdmissionLock) {
                    if (activeRequestId == requestId) {
                        activeRequestId = null
                        conversation = null
                    }
                }
                activeConversation.close()
            }
            if (resourceFailure != null) {
                unloadOwned()
                throw IllegalStateException("inference_denied:" + resourceFailure)
            }
            val elapsed = (System.nanoTime() - started) / 1_000_000_000.0
            val cancelled = cancellationRegistry.finish(requestId) || cancellationObserved
            InferenceOutcome(
                text = if (cancelled) "" else response.toString(),
                elapsedSeconds = elapsed,
                deadlineMet = deadlineMet && elapsed <= budgetSeconds,
                taskClass = taskClass,
                status = if (cancelled) "cancelled" else "completed",
            )
        }) {
            override fun done() {
                cancellationRegistry.finish(requestId)
            }
        }
        synchronized(inferenceAdmissionLock) {
            pruneExpiredRequests()
            if (inferenceJobs.containsKey(requestId) || resultRetention.isKnown(requestId)) {
                return "duplicate"
            }
            if (inferenceJobs.size >= 16) return "queue_full"
            if (inferenceJobs.size + resultRetention.retainedCount() >= 32) {
                return "result_ack_required"
            }
            val previous = inferenceJobs.putIfAbsent(requestId, future)
            if (previous != null) return "duplicate"
            if (!cancellationRegistry.register(requestId)) {
                inferenceJobs.remove(requestId, future)
                return "duplicate"
            }
            inferenceSubmittedAt[requestId] = System.nanoTime()
            try {
                executor.execute(future)
            } catch (failure: RuntimeException) {
                inferenceJobs.remove(requestId, future)
                inferenceSubmittedAt.remove(requestId)
                cancellationRegistry.forget(requestId)
                throw failure
            }
        }
        return "accepted"
    }

    private fun evaluateLoad(file: File, backendName: String): Pair<Boolean, String> {
        if (!ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = isBackgroundScheduleAuthorized(),
                screenInteractive = isScreenInteractive(),
                charging = isCharging()
            )
        ) return Pair(false, "background_load_not_authorized")
        if (!ModelRuntimeAdmissionPolicy.isBackendAllowed(backendName)) {
            return Pair(false, "backend_not_authorized")
        }
        val memory = ActivityManager.MemoryInfo()
        (appContext.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager)
            .getMemoryInfo(memory)
        val sizeMb = file.length().toDouble() / (1024.0 * 1024.0)
        val totalRamMb = memory.totalMem.toDouble() / (1024.0 * 1024.0)
        val requiredMb = ModelBudgetMath.requiredLoadRamMb(sizeMb, backendName, totalRamMb).toDouble()
        val availableMb = memory.availMem.toDouble() / (1024.0 * 1024.0)
        if (availableMb < requiredMb) return Pair(false, "insufficient_available_ram")
        if (thermalStatus() >= PowerManager.THERMAL_STATUS_SEVERE) {
            return Pair(false, "thermal_state_blocks_model_load")
        }
        val cacheSpace = StatFs(appContext.cacheDir.absolutePath).availableBytes
        val requiredCacheMb = ModelBudgetMath.requiredCacheStorageMb(sizeMb)
        if (cacheSpace < requiredCacheMb * 1024L * 1024L) {
            return Pair(false, "insufficient_cache_storage")
        }
        return Pair(true, "admitted")
    }

    private fun evaluateInference(
        taskClass: String,
        requestedAdditionalRamMb: Long?,
        allowBackground: Boolean,
    ): Pair<Boolean, String> {
        if (!ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = allowBackground,
                taskClass = taskClass,
                backgroundScheduleEnabled = isBackgroundScheduleAuthorized(),
                screenInteractive = isScreenInteractive(),
                charging = isCharging()
            )
        ) return Pair(false, "background_inference_not_authorized")
        val memory = ActivityManager.MemoryInfo()
        (appContext.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager)
            .getMemoryInfo(memory)
        val totalRamMb = memory.totalMem.toDouble() / (1024.0 * 1024.0)
        val requiredMb = ModelBudgetMath.requiredInferenceRamMb(
            taskClass, requestedAdditionalRamMb, totalRamMb
        ).toDouble()
        val availableMb = memory.availMem.toDouble() / (1024.0 * 1024.0)
        if (availableMb < requiredMb) return Pair(false, "insufficient_inference_headroom")
        if (thermalStatus() >= PowerManager.THERMAL_STATUS_SEVERE) {
            return Pair(false, "thermal_state_blocks_inference")
        }
        return Pair(true, "admitted")
    }

    private fun isBackgroundScheduleAuthorized(): Boolean {
        return WorkPolicy.supportsAuthenticatedWake(android.os.Build.VERSION.SDK_INT)
            && WorkScheduler.isEnabled(appContext)
    }

    private fun isAppForeground(): Boolean {
        val processInfo = ActivityManager.RunningAppProcessInfo()
        ActivityManager.getMyMemoryState(processInfo)
        return processInfo.importance <=
            ActivityManager.RunningAppProcessInfo.IMPORTANCE_VISIBLE
    }

    private fun isScreenInteractive(): Boolean {
        return try {
            (appContext.getSystemService(Context.POWER_SERVICE) as PowerManager).isInteractive
        } catch (_: Exception) {
            false
        }
    }

    private fun availableRamMb(): Long {
        val memory = ActivityManager.MemoryInfo()
        (appContext.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager)
            .getMemoryInfo(memory)
        return memory.availMem / (1024L * 1024L)
    }

    private fun thermalStatus(): Int {
        if (android.os.Build.VERSION.SDK_INT < 29) return PowerManager.THERMAL_STATUS_NONE
        return try {
            (appContext.getSystemService(Context.POWER_SERVICE) as PowerManager).currentThermalStatus
        } catch (_: Exception) {
            PowerManager.THERMAL_STATUS_NONE
        }
    }

    private fun batteryPercent(): Int? {
        val intent = appContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: return null
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return null
        return (level * 100) / scale
    }

    private fun isCharging(): Boolean {
        val intent = appContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: return false
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        return status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
    }

    private fun response(
        state: String,
        requestId: String? = null,
        error: String? = null,
    ) = Bundle().apply {
        putString("status", state)
        requestId?.let { putString("request_id", it) }
        error?.let { putString("error", it) }
    }

    fun pollInference(requestId: String): Bundle {
        pruneExpiredRequests()
        resultRetention.get(requestId)?.let { return it.toBundle(requestId) }
        if (resultRetention.isKnown(requestId)) {
            return response("acknowledged", requestId = requestId)
        }
        val future = inferenceJobs[requestId]
            ?: return Bundle().apply { putString("status", "unknown_request") }
        if (!future.isDone) {
            return Bundle().apply {
                putString("status", "pending")
                putString("request_id", requestId)
            }
        }

        val retained = try {
            val result = future.get()
            RetainedInferenceResult(
                status = result.status,
                text = result.text,
                elapsedSeconds = result.elapsedSeconds,
                deadlineMet = result.deadlineMet,
                taskClass = result.taskClass,
            )
        } catch (failure: Throwable) {
            val cause = failure.cause ?: failure
            if (cause is VirtualMachineError || cause is ThreadDeath) throw cause
            val wasCancelled = cancellationRegistry.isCancellationRequested(requestId)
            RetainedInferenceResult(
                status = if (wasCancelled) "cancelled" else "failed",
                error = if (wasCancelled) null else cause.javaClass.simpleName,
            )
        }
        return synchronized(inferenceAdmissionLock) {
            if (!inferenceJobs.remove(requestId, future)) {
                return@synchronized resultRetention.get(requestId)?.toBundle(requestId)
                    ?: response("unknown_request", requestId = requestId)
            }
            inferenceSubmittedAt.remove(requestId)
            resultRetention.retain(requestId, retained)
            cancellationRegistry.forget(requestId)
            resultRetention.get(requestId)?.toBundle(requestId)
                ?: response("failed", requestId = requestId, error = "result_retention_unavailable")
        }
    }

    fun cancelInference(requestId: String): Bundle {
        if (requestId.isBlank()) return response("failed", error = "request_id_required")
        val cancellationAndConversation = synchronized(inferenceAdmissionLock) {
            pruneExpiredRequests()
            if (resultRetention.isKnown(requestId)) {
                return response("already_completed", requestId = requestId)
            }
            if (!inferenceJobs.containsKey(requestId)) {
                return response("unknown_request", requestId = requestId)
            }
            val state = cancellationRegistry.requestCancellation(requestId)
            val active = if (activeRequestId == requestId) conversation else null
            Pair(state, active)
        }
        val cancellation = cancellationAndConversation.first
        val active = cancellationAndConversation.second
        if (cancellation == InferenceCancellationRegistry.CancelResult.ALREADY_COMPLETED) {
            return response("already_completed", requestId = requestId)
        }
        if (cancellation == InferenceCancellationRegistry.CancelResult.UNKNOWN) {
            return response("unknown_request", requestId = requestId)
        }
        if (cancellation == InferenceCancellationRegistry.CancelResult.REQUESTED && active != null) {
            try {
                active.cancelProcess()
            } catch (_: IllegalStateException) {
                // Completion may win the race after the request-scoped cancellation was recorded.
            }
        }
        return response("cancellation_requested", requestId = requestId)
    }

    fun acknowledgeInference(requestId: String): Bundle {
        if (requestId.isBlank()) {
            return response("failed", error = "request_id_required")
        }
        return synchronized(inferenceAdmissionLock) {
            pruneExpiredRequests()
            if (inferenceJobs.containsKey(requestId)) {
                return@synchronized response("not_completed", requestId = requestId)
            }
            when (resultRetention.acknowledge(requestId)) {
                InferenceResultRetention.AckStatus.ACKNOWLEDGED ->
                    response("acknowledged", requestId = requestId)
                InferenceResultRetention.AckStatus.ALREADY_ACKNOWLEDGED ->
                    response("already_acknowledged", requestId = requestId)
                InferenceResultRetention.AckStatus.UNKNOWN ->
                    response("unknown_request", requestId = requestId)
                InferenceResultRetention.AckStatus.CAPACITY ->
                    response("ack_capacity_reached", requestId = requestId)
            }
        }
    }

    private fun pruneExpiredRequests() = synchronized(inferenceAdmissionLock) {
        resultRetention.pruneExpired()
        val now = System.nanoTime()
        for ((requestId, submittedAt) in inferenceSubmittedAt.entries) {
            val future = inferenceJobs[requestId]
            if (future == null) {
                inferenceSubmittedAt.remove(requestId, submittedAt)
            } else if (future.isDone && now - submittedAt >= requestRetentionTtlNanos) {
                inferenceJobs.remove(requestId, future)
                inferenceSubmittedAt.remove(requestId, submittedAt)
                cancellationRegistry.forget(requestId)
            }
        }
    }

    private fun RetainedInferenceResult.toBundle(requestId: String): Bundle = Bundle().apply {
        putString("status", status)
        putString("request_id", requestId)
        text?.let { putString("text", it) }
        elapsedSeconds?.let { putDouble("elapsed_seconds", it) }
        deadlineMet?.let { putBoolean("deadline_met", it) }
        taskClass?.let { putString("task_class", it) }
        error?.let { putString("error", it) }
    }

    fun unload(): Future<String> = executor.submit<String> {
        unloadOwned()
        "unloaded"
    }

    private class RequestCancellationException : RuntimeException()

    private class ResourceLimitCancellationException(val reason: String) : RuntimeException()

    private fun unloadOwned() {
        memoryPressureRequested.set(false)
        val activeConversation = conversation
        val activeEngine = engine
        conversation = null
        engine = null
        loaded = false
        currentModelPath = null
        currentBackendName = null
        try {
            activeConversation?.close()
        } finally {
            try {
                activeEngine?.close()
            } finally {
                lifecycleStatus = "unloaded"
            }
        }
    }

    fun unloadForMemoryPressure() {
        if (loaded || lifecycleStatus == "loading") {
            memoryPressureRequested.set(true)
            // cancelProcess is designed to interrupt an active stream from the caller thread;
            // do not wait for another output chunk before the owner executor can unload.
            try {
                conversation?.cancelProcess()
            } catch (_: IllegalStateException) {
                // The stream may have completed between the volatile read and cancellation.
            }
            unload()
        }
    }

    fun shutdown() {
        try {
            unload().get(30, TimeUnit.SECONDS)
        } catch (_: Exception) {
            // Process teardown must not block indefinitely on native cleanup.
        } finally {
            executor.shutdown()
        }
    }
}
