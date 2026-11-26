package com.mahoraga.runtime

import org.junit.Assert.assertEquals
import org.junit.Test

class ModelSamplingDefaultsTest {
    @Test
    fun defaultsMatchQwen3ThinkingRecommendations() {
        assertEquals(
            ModelSamplingParameters(topK = 20, topP = 0.95, temperature = 0.6),
            ModelSamplingDefaults.resolve(null, null, null),
        )
    }

    @Test
    fun explicitValuesOverrideOnlyTheirOwnDefaults() {
        assertEquals(
            ModelSamplingParameters(topK = 32, topP = 0.95, temperature = 0.4),
            ModelSamplingDefaults.resolve(32, null, 0.4),
        )
    }
}
