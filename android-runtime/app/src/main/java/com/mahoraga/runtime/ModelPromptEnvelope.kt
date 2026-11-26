package com.mahoraga.runtime

import org.json.JSONException
import org.json.JSONObject

internal data class PromptTurn(
    val role: String,
    val content: String,
)

internal data class ParsedModelPrompt(
    val systemInstruction: String?,
    val initialMessages: List<PromptTurn>,
    val finalUserMessage: String,
)

/**
 * Parses the same versioned envelope emitted by ModelRuntimeGenerationAdapter.
 *
 * Plain text remains supported for legacy callers. A recognized but malformed
 * envelope fails closed rather than being sent to the model as opaque JSON text.
 */
internal object ModelPromptEnvelope {
    const val FORMAT = "mahoraga_messages_v1"
    private const val MAX_MESSAGES = 32
    private const val MAX_MESSAGE_CHARS = 20_000
    private const val MAX_TOTAL_CHARS = 50_000

    fun parse(prompt: String): ParsedModelPrompt {
        val looksLikeEnvelope = prompt.trimStart().startsWith("{") &&
            prompt.contains(FORMAT)
        val root = try {
            JSONObject(prompt)
        } catch (failure: JSONException) {
            if (looksLikeEnvelope) {
                throw IllegalArgumentException("prompt_envelope_invalid_json", failure)
            }
            return ParsedModelPrompt(
                systemInstruction = null,
                initialMessages = emptyList(),
                finalUserMessage = prompt,
            )
        }

        if (root.opt("format") != FORMAT) {
            return ParsedModelPrompt(
                systemInstruction = null,
                initialMessages = emptyList(),
                finalUserMessage = prompt,
            )
        }

        val messages = root.optJSONArray("messages")
            ?: throw IllegalArgumentException("prompt_envelope_messages_required")
        require(messages.length() in 1..MAX_MESSAGES) {
            "prompt_envelope_message_count_invalid"
        }

        var totalChars = 0
        var seenConversationTurn = false
        val turns = (0 until messages.length()).map { index ->
            val item = messages.optJSONObject(index)
                ?: throw IllegalArgumentException("prompt_envelope_message_invalid")
            val role = item.opt("role") as? String
                ?: throw IllegalArgumentException("prompt_envelope_role_invalid")
            require(role in setOf("system", "user", "assistant")) {
                "prompt_envelope_role_unsupported"
            }
            val text = item.opt("content") as? String
                ?: throw IllegalArgumentException("prompt_envelope_content_invalid")
            require(text.isNotBlank()) { "prompt_envelope_content_empty" }
            require(text.length <= MAX_MESSAGE_CHARS) {
                "prompt_envelope_message_too_large"
            }
            totalChars += text.length
            require(totalChars <= MAX_TOTAL_CHARS) {
                "prompt_envelope_total_too_large"
            }
            if (role == "system" && seenConversationTurn) {
                throw IllegalArgumentException("prompt_envelope_system_message_out_of_order")
            }
            if (role != "system") seenConversationTurn = true
            PromptTurn(role, text)
        }

        require(turns.last().role == "user") {
            "prompt_envelope_final_message_must_be_user"
        }

        val systemText = turns
            .filter { it.role == "system" }
            .joinToString("\n\n") { it.content }
            .takeIf { it.isNotBlank() }
        val initial = turns.dropLast(1).filter { it.role != "system" }

        return ParsedModelPrompt(
            systemInstruction = systemText,
            initialMessages = initial,
            finalUserMessage = turns.last().content,
        )
    }
}
