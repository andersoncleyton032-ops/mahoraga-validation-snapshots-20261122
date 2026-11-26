package com.mahoraga.runtime

/** Qwen3 thinking-mode sampler defaults, independently testable from LiteRT. */
internal data class ModelSamplingParameters(
    val topK: Int,
    val topP: Double,
    val temperature: Double,
)

internal object ModelSamplingDefaults {
    const val TOP_K = 20
    const val TOP_P = 0.95
    const val TEMPERATURE = 0.6

    fun resolve(topK: Int?, topP: Double?, temperature: Double?) =
        ModelSamplingParameters(
            topK = topK ?: TOP_K,
            topP = topP ?: TOP_P,
            temperature = temperature ?: TEMPERATURE,
        )
}
