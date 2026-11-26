package com.mahoraga.runtime

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TermuxCallerPolicyTest {
    @Test
    fun acceptsOnlyInstalledTermuxUidWithTrustedSigner() {
        assertTrue(
            TermuxCallerPolicy.isTrusted(
                callingUid = 10456,
                packagesForUid = arrayOf("com.termux"),
                installedTermuxUid = 10456,
                signerTrusted = true
            )
        )
    }

    @Test
    fun rejectsUidMismatch() {
        assertFalse(
            TermuxCallerPolicy.isTrusted(
                callingUid = 10457,
                packagesForUid = arrayOf("com.termux"),
                installedTermuxUid = 10456,
                signerTrusted = true
            )
        )
    }

    @Test
    fun rejectsPackageMismatch() {
        assertFalse(
            TermuxCallerPolicy.isTrusted(
                callingUid = 10456,
                packagesForUid = arrayOf("com.example.other"),
                installedTermuxUid = 10456,
                signerTrusted = true
            )
        )
    }

    @Test
    fun rejectsUntrustedSigner() {
        assertFalse(
            TermuxCallerPolicy.isTrusted(
                callingUid = 10456,
                packagesForUid = arrayOf("com.termux"),
                installedTermuxUid = 10456,
                signerTrusted = false
            )
        )
    }

    @Test
    fun rejectsUnknownOrInvalidUidAndMissingPackages() {
        assertFalse(
            TermuxCallerPolicy.isTrusted(
                callingUid = -1,
                packagesForUid = arrayOf("com.termux"),
                installedTermuxUid = 10456,
                signerTrusted = true
            )
        )
        assertFalse(
            TermuxCallerPolicy.isTrusted(
                callingUid = 10456,
                packagesForUid = null,
                installedTermuxUid = 10456,
                signerTrusted = true
            )
        )
    }
}
