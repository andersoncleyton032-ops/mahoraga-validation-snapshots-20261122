package com.mahoraga.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ModelPromptEnvelopeTest {
    private fun fixture(name: String): String =
        requireNotNull(javaClass.classLoader?.getResource(name)) {
            "missing shared prompt fixture: $name"
        }.readText()
    @Test
    fun parsesSystemHistoryAndFinalUserTurn() {
        val prompt = fixture("mahoraga_messages_v1_valid.json")

        val parsed = ModelPromptEnvelope.parse(prompt)

        assertEquals("Você é Mahoraga.", parsed.systemInstruction)
        assertEquals(
            listOf(
                PromptTurn("user", "Pergunta anterior."),
                PromptTurn("assistant", "Resposta anterior."),
            ),
            parsed.initialMessages,
        )
        assertEquals("Pergunta atual.", parsed.finalUserMessage)
    }

    @Test
    fun combinesMultipleSystemMessagesAndKeepsConversationOrder() {
        val prompt = """
            {"format":"mahoraga_messages_v1","messages":[
              {"role":"system","content":"Instrução A"},
              {"role":"system","content":"Instrução B"},
              {"role":"user","content":"Pergunta"}
            ]}
        """.trimIndent()

        val parsed = ModelPromptEnvelope.parse(prompt)

        assertEquals("Instrução A\n\nInstrução B", parsed.systemInstruction)
        assertEquals(emptyList<PromptTurn>(), parsed.initialMessages)
        assertEquals("Pergunta", parsed.finalUserMessage)
    }

    @Test
    fun preservesLegacyPlainTextPrompt() {
        val parsed = ModelPromptEnvelope.parse("pergunta simples")
        assertNull(parsed.systemInstruction)
        assertEquals(emptyList<PromptTurn>(), parsed.initialMessages)
        assertEquals("pergunta simples", parsed.finalUserMessage)
    }

    @Test
    fun rejectsUnsupportedToolRole() {
        val prompt = """
            {"format":"mahoraga_messages_v1","messages":[
              {"role":"tool","content":"resultado"},
              {"role":"user","content":"continue"}
            ]}
        """.trimIndent()

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("tool role must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_role_unsupported", expected.message)
        }
    }

    @Test
    fun rejectsNonUserFinalMessage() {
        val prompt = """
            {"format":"mahoraga_messages_v1","messages":[
              {"role":"user","content":"pergunta"},
              {"role":"assistant","content":"resposta anterior"}
            ]}
        """.trimIndent()

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("final assistant turn must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_final_message_must_be_user", expected.message)
        }
    }

    @Test
    fun rejectsEmptyContent() {
        val prompt = """
            {"format":"mahoraga_messages_v1","messages":[
              {"role":"user","content":" "}
            ]}
        """.trimIndent()

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("empty content must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_content_empty", expected.message)
        }
    }

    @Test
    fun rejectsMalformedRecognizedEnvelopeInsteadOfTreatingItAsPlainText() {
        val prompt = """{"format":"mahoraga_messages_v1","messages":[ """

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("malformed envelope must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_invalid_json", expected.message)
        }
    }
}


    @Test
    fun rejectsSystemMessageAfterConversationHistory() {
        val prompt = fixture("mahoraga_messages_v1_invalid_system_order.json")

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("late system message must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_system_message_out_of_order", expected.message)
        }
    }

    @Test
    fun rejectsMessageAboveSharedCharacterLimit() {
        val oversized = "x".repeat(20_001)
        val prompt = """
            {"format":"mahoraga_messages_v1","messages":[
              {"role":"user","content":"$oversized"}
            ]}
        """.trimIndent()

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("oversized message must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_message_too_large", expected.message)
        }
    }

    @Test
    fun rejectsTotalContextAboveSharedCharacterLimit() {
        val part = "x".repeat(17_000)
        val prompt = """
            {"format":"mahoraga_messages_v1","messages":[
              {"role":"user","content":"$part"},
              {"role":"assistant","content":"$part"},
              {"role":"user","content":"$part"}
            ]}
        """.trimIndent()

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("oversized total context must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_total_too_large", expected.message)
        }
    }

    @Test
    fun rejectsMoreThanSharedMaximumMessageCount() {
        val messages = (0..32).joinToString(",") {
            """{"role":"user","content":"turn-$it"}"""
        }
        val prompt = """{"format":"mahoraga_messages_v1","messages":[$messages]}"""

        try {
            ModelPromptEnvelope.parse(prompt)
            throw AssertionError("too many messages must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertEquals("prompt_envelope_message_count_invalid", expected.message)
        }
    }
