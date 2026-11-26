package com.mahoraga.runtime

import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.security.MessageDigest
import java.util.Locale

internal object ModelArtifactIntegrity {
    data class Verification(
        val trusted: Boolean,
        val actualSha256: String?,
        val reason: String?
    )

    fun verify(file: File, expectedSha256: String?): Verification {
        val expected = normalize(expectedSha256)
            ?: return Verification(false, null, "expected_sha256_invalid")
        if (!file.isFile || !file.canRead()) {
            return Verification(false, null, "model_file_unavailable")
        }
        return try {
            val actual = sha256(file)
            Verification(
                trusted = MessageDigest.isEqual(
                    actual.toByteArray(Charsets.US_ASCII),
                    expected.toByteArray(Charsets.US_ASCII)
                ),
                actualSha256 = actual,
                reason = if (actual == expected) null else "model_sha256_mismatch"
            )
        } catch (failure: java.security.NoSuchAlgorithmException) {
            Verification(false, null, "model_sha256_unavailable")
        } catch (failure: IOException) {
            Verification(false, null, "model_sha256_io_error")
        } catch (failure: SecurityException) {
            Verification(false, null, "model_sha256_access_denied")
        }
    }

    fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                if (count > 0) digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { byte ->
            "%02X".format(Locale.ROOT, byte.toInt() and 0xff)
        }
    }

    private fun normalize(value: String?): String? {
        if (value == null) return null
        val normalized = value.replace(":", "")
            .filterNot { it.isWhitespace() }
            .uppercase(Locale.ROOT)
        if (normalized.length != 64) return null
        if (normalized.any { it !in '0'..'9' && it !in 'A'..'F' }) return null
        return normalized
    }
}
