package com.mahoraga.runtime

import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min

/**
 * Pure budget calculations separated from Android service access for deterministic tests.
 * Values are estimates and remain configurable through each task request.
 */
internal object ModelBudgetMath {
    fun requiredLoadRamMb(
        modelSizeMb: Double,
        backendName: String,
        totalRamMb: Double,
    ): Long {
        require(modelSizeMb > 0.0 && totalRamMb > 0.0)
        val gpu = backendName == "gpu"
        val estimatedPeak = if (gpu) {
            ceil(max(1024.0, modelSizeMb * 0.75 + 512.0))
        } else {
            ceil(modelSizeMb * 1.5 + 1_152.0)
        }
        val osReserve = max(512.0, totalRamMb * 0.08)
        return ceil(estimatedPeak + osReserve).toLong()
    }

    fun requiredCacheStorageMb(modelSizeMb: Double): Long {
        require(modelSizeMb > 0.0)
        return max(256.0, ceil(modelSizeMb * 0.10)).toLong()
    }

    fun requiredInferenceRamMb(
        taskClass: String,
        requestedAdditionalRamMb: Long?,
        totalRamMb: Double,
    ): Long {
        require(totalRamMb > 0.0)
        val baseline = when (taskClass) {
            "reasoning" -> 768L
            "maintenance" -> 384L
            "background" -> 256L
            "interactive" -> 512L
            else -> throw IllegalArgumentException("task_class_invalid")
        }
        val additional = max(baseline, requestedAdditionalRamMb ?: 0L)
        val osReserve = max(384.0, totalRamMb * 0.04)
        return ceil(additional + osReserve).toLong()
    }

    fun thinkingTokenBudget(taskClass: String, requested: Int?): Int {
        val baseline = when (taskClass) {
            "interactive" -> 256
            "reasoning" -> 1024
            "maintenance" -> 512
            "background" -> 256
            else -> throw IllegalArgumentException("task_class_invalid")
        }
        require(requested == null || requested in 0..2048)
        return requested ?: baseline
    }

    fun maxOutputTokens(taskClass: String, requested: Int?): Int {
        val baseline = when (taskClass) {
            "interactive" -> 512
            "reasoning" -> 1024
            "maintenance" -> 768
            "background" -> 512
            else -> throw IllegalArgumentException("task_class_invalid")
        }
        require(requested == null || requested in 1..2048)
        return requested ?: baseline
    }

    fun totalOutputTokenLimit(thinkingTokens: Int, finalOutputTokens: Int): Int {
        require(thinkingTokens >= 0 && finalOutputTokens > 0)
        return Math.addExact(thinkingTokens, finalOutputTokens)
    }

    fun validateContextBudget(
        promptChars: Int,
        thinkingTokens: Int,
        outputTokens: Int,
        contextWindowTokens: Int = 4096,
    ) {
        require(promptChars > 0 && thinkingTokens >= 0 && outputTokens > 0)
        val estimatedInputTokens = kotlin.math.ceil(promptChars / 3.0).toInt()
        require(estimatedInputTokens + thinkingTokens + outputTokens <= contextWindowTokens) {
            "prompt_and_generation_exceed_context_window"
        }
    }

    private const val MAX_DURATION_MULTIPLIER = 2.0

    private fun defaultDurationSeconds(taskClass: String): Double = when (taskClass) {
        "reasoning" -> 120.0
        "maintenance" -> 180.0
        "background" -> 300.0
        "interactive" -> 30.0
        else -> throw IllegalArgumentException("task_class_invalid")
    }

    fun durationSeconds(
        taskClass: String,
        requestedSeconds: Double?,
        thermalStatus: Int,
        moderateThermalStatus: Int,
        batteryPercent: Int?,
        charging: Boolean,
    ): Double {
        // Validate the class even when the caller supplies an explicit duration.
        val default = defaultDurationSeconds(taskClass)
        require(
            requestedSeconds == null ||
                (requestedSeconds.isFinite() && requestedSeconds > 0.0)
        ) { "requested_duration_invalid" }

        // The external Termux request is only a hint. Keep a task-specific ceiling
        // so a caller cannot turn a bounded inference into an effectively endless job.
        val maximum = default * MAX_DURATION_MULTIPLIER
        val base = min(requestedSeconds ?: default, maximum)
        var result = base
        if (thermalStatus >= moderateThermalStatus) result *= 0.75
        if (batteryPercent != null && batteryPercent < 15 && !charging) result *= 0.6
        return max(1.0, min(result, maximum))
    }
}
