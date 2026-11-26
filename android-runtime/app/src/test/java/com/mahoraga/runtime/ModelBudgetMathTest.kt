package com.mahoraga.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelBudgetMathTest {
    @Test
    fun loadBudgetScalesWithArtifactSizeAndBackend() {
        val int4Cpu = ModelBudgetMath.requiredLoadRamMb(932.0, "cpu", 12_288.0)
        val int8Cpu = ModelBudgetMath.requiredLoadRamMb(1_674.0, "cpu", 12_288.0)
        val int4Gpu = ModelBudgetMath.requiredLoadRamMb(932.0, "gpu", 12_288.0)
        val int8Gpu = ModelBudgetMath.requiredLoadRamMb(1_674.0, "gpu", 12_288.0)
        assertEquals(3_534L, int4Cpu)
        assertTrue(int8Cpu > int4Cpu)
        assertTrue(int8Gpu < int8Cpu)
        assertTrue(int8Gpu > int4Gpu)
    }

    @Test
    fun cacheStorageReserveScalesWithArtifactSize() {
        assertEquals(256L, ModelBudgetMath.requiredCacheStorageMb(932.0))
        assertTrue(
            ModelBudgetMath.requiredCacheStorageMb(4_000.0) >
                ModelBudgetMath.requiredCacheStorageMb(932.0)
        )
    }

    @Test
    fun inferenceBudgetVariesByTaskAndCannotBeLoweredBelowBaseline() {
        val interactive = ModelBudgetMath.requiredInferenceRamMb("interactive", null, 12_288.0)
        val reasoning = ModelBudgetMath.requiredInferenceRamMb("reasoning", null, 12_288.0)
        val maintenance = ModelBudgetMath.requiredInferenceRamMb("maintenance", null, 12_288.0)
        val requestedTiny = ModelBudgetMath.requiredInferenceRamMb("reasoning", 1L, 12_288.0)
        val requestedLarge = ModelBudgetMath.requiredInferenceRamMb("interactive", 2_048L, 12_288.0)
        assertTrue(reasoning > interactive)
        assertTrue(interactive > maintenance)
        assertEquals(reasoning, requestedTiny)
        assertTrue(requestedLarge > interactive)
    }

    @Test
    fun taskDurationTargetsAreDistinctAndContextuallyDerated() {
        val interactive = ModelBudgetMath.durationSeconds("interactive", null, 0, 1, 100, true)
        val reasoning = ModelBudgetMath.durationSeconds("reasoning", null, 0, 1, 100, true)
        val reasoningWarm = ModelBudgetMath.durationSeconds("reasoning", null, 2, 1, 100, true)
        val reasoningLowBattery = ModelBudgetMath.durationSeconds("reasoning", null, 0, 1, 10, false)
        val explicit = ModelBudgetMath.durationSeconds("reasoning", 150.0, 0, 1, 100, true)
        assertTrue(reasoning > interactive)
        assertTrue(reasoningWarm < reasoning)
        assertTrue(reasoningLowBattery < reasoning)
        assertEquals(150.0, explicit, 0.001)
    }

    @Test(expected = IllegalArgumentException::class)
    fun unknownTaskClassIsRejected() {
        ModelBudgetMath.requiredInferenceRamMb("unbounded", null, 12_288.0)
    }

    @Test
    fun contextBudgetRejectsPromptAndGenerationOverflow() {
        ModelBudgetMath.validateContextBudget(6_000, 1_024, 1_024)
        try {
            ModelBudgetMath.validateContextBudget(9_000, 1_024, 1_024)
            throw AssertionError("Expected context window rejection")
        } catch (_: IllegalArgumentException) {
            // Expected: estimated input plus thinking and output exceed 4096.
        }
    }

    @Test
    fun thinkingCanBeDisabledForSimpleTasks() {
        assertEquals(0, ModelBudgetMath.thinkingTokenBudget("interactive", 0))
        assertEquals(1, ModelBudgetMath.maxOutputTokens("interactive", 1))
    }

    @Test
    fun totalOutputLimitReservesThinkingAndFinalAnswerTokens() {
        assertEquals(768, ModelBudgetMath.totalOutputTokenLimit(256, 512))
        assertEquals(2048, ModelBudgetMath.totalOutputTokenLimit(1024, 1024))
    }

    @Test(expected = IllegalArgumentException::class)
    fun totalOutputLimitRejectsInvalidBudgets() {
        ModelBudgetMath.totalOutputTokenLimit(-1, 512)
    }


    @Test
    fun explicitDurationIsCappedByTaskClass() {
        assertEquals(
            60.0,
            ModelBudgetMath.durationSeconds("interactive", Double.MAX_VALUE, 0, 1, 100, true),
            0.001
        )
        assertEquals(
            240.0,
            ModelBudgetMath.durationSeconds("reasoning", Double.MAX_VALUE, 0, 1, 100, true),
            0.001
        )
        assertEquals(
            360.0,
            ModelBudgetMath.durationSeconds("maintenance", Double.MAX_VALUE, 0, 1, 100, true),
            0.001
        )
        assertEquals(
            600.0,
            ModelBudgetMath.durationSeconds("background", Double.MAX_VALUE, 0, 1, 100, true),
            0.001
        )
    }

    @Test
    fun durationRejectsNonFiniteAndNonPositiveRequests() {
        val invalid = listOf(
            0.0,
            -1.0,
            Double.NaN,
            Double.POSITIVE_INFINITY,
            Double.NEGATIVE_INFINITY,
        )
        for (value in invalid) {
            try {
                ModelBudgetMath.durationSeconds("interactive", value, 0, 1, 100, true)
                throw AssertionError("Expected invalid duration to be rejected: $value")
            } catch (_: IllegalArgumentException) {
                // Expected.
            }
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun unknownTaskClassIsRejectedEvenWithExplicitDuration() {
        ModelBudgetMath.durationSeconds("unknown", 10.0, 0, 1, 100, true)
    }

}
