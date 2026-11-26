package com.mahoraga.runtime

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ModelArtifactIntegrityTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun verifiesStreamingSha256ForKnownContent() {
        val file = temporaryFolder.newFile("model.litertlm")
        file.writeText("abc", Charsets.UTF_8)

        val result = ModelArtifactIntegrity.verify(
            file,
            "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"
        )

        assertTrue(result.trusted)
        assertEquals(
            "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD",
            result.actualSha256
        )
        assertEquals(null, result.reason)
    }

    @Test
    fun rejectsChangedArtifact() {
        val file = temporaryFolder.newFile("model.litertlm")
        file.writeText("changed", Charsets.UTF_8)

        val result = ModelArtifactIntegrity.verify(
            file,
            "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"
        )

        assertFalse(result.trusted)
        assertEquals("model_sha256_mismatch", result.reason)
    }

    @Test
    fun rejectsMalformedExpectedDigest() {
        val file = temporaryFolder.newFile("model.litertlm")
        file.writeText("abc", Charsets.UTF_8)

        val result = ModelArtifactIntegrity.verify(file, "not-a-sha256")
        assertFalse(result.trusted)
        assertEquals("expected_sha256_invalid", result.reason)
    }

    @Test
    fun rejectsMissingArtifact() {
        val missing = File(temporaryFolder.root, "missing.litertlm")
        val result = ModelArtifactIntegrity.verify(
            missing,
            "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"
        )
        assertFalse(result.trusted)
        assertEquals("model_file_unavailable", result.reason)
    }
}
