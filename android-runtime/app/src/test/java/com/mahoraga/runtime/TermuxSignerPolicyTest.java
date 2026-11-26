package com.mahoraga.runtime;

import android.content.pm.PackageManager;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

public final class TermuxSignerPolicyTest {
    @Test
    public void recognizesOfficialTermuxReleaseSigners() {
        assertEquals("F-Droid", TermuxSignerPolicy.sourceForFingerprint(
                TermuxSignerPolicy.FDROID_SHA256
        ));
        assertEquals("GitHub release", TermuxSignerPolicy.sourceForFingerprint(
                TermuxSignerPolicy.GITHUB_SHA256
        ));
        assertEquals("Google Play", TermuxSignerPolicy.sourceForFingerprint(
                TermuxSignerPolicy.GOOGLE_PLAY_SHA256
        ));
        assertEquals("Termux Devs", TermuxSignerPolicy.sourceForFingerprint(
                TermuxSignerPolicy.TERMUX_DEVS_SHA256
        ));
    }

    @Test
    public void normalizesColonSeparatedLowercaseFingerprint() {
        String colonSeparated = TermuxSignerPolicy.FDROID_SHA256
                .toLowerCase(java.util.Locale.ROOT)
                .replaceAll("(.{2})", "$1:");
        colonSeparated = colonSeparated.substring(0, colonSeparated.length() - 1);

        assertEquals(
                TermuxSignerPolicy.FDROID_SHA256,
                TermuxSignerPolicy.normalizeFingerprint(colonSeparated)
        );
        assertTrue(TermuxSignerPolicy.verifyFingerprint(colonSeparated).trusted);
    }

    @Test
    public void rejectsUnknownAndMalformedFingerprints() {
        String unknown = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

        assertNull(TermuxSignerPolicy.sourceForFingerprint(unknown));
        assertFalse(TermuxSignerPolicy.verifyFingerprint(unknown).trusted);
        assertFalse(TermuxSignerPolicy.verifyFingerprint("not-a-certificate").trusted);
        assertFalse(TermuxSignerPolicy.verifyFingerprint(null).trusted);
    }

    @Test
    public void selectsSigningInfoApiByPlatformLevel() {
        assertEquals(
                PackageManager.GET_SIGNATURES,
                TermuxSignerPolicy.packageInfoFlags(27)
        );
        assertEquals(
                PackageManager.GET_SIGNING_CERTIFICATES,
                TermuxSignerPolicy.packageInfoFlags(28)
        );
        assertEquals(
                PackageManager.GET_SIGNING_CERTIFICATES,
                TermuxSignerPolicy.packageInfoFlags(36)
        );
    }

    @Test
    public void rejectedVerificationDoesNotExposeTrustedSource() {
        TermuxSignerPolicy.Verification verification =
                TermuxSignerPolicy.verifyFingerprint("unknown");

        assertFalse(verification.trusted);
        assertNull(verification.source);
        assertNull(verification.fingerprint);
        assertEquals("unrecognized_termux_signer", verification.reason);
    }
}
