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
        assertEquals(
                "228FB2CFE90831C1499EC3CCAF61E96E8E1CE70766B9474672CE427334D41C42",
                TermuxSignerPolicy.FDROID_SHA256
        );
        assertEquals(
                "B6DA01480EEFD5FBF2CD3771B8D1021EC791304BDD6C4BF41D3FAABAD48EE5E1",
                TermuxSignerPolicy.GITHUB_SHA256
        );
        assertEquals(
                "738F0A30A04D3C8A1BE304AF18D0779BCF3EA88FB60808F657A3521861C2EBF9",
                TermuxSignerPolicy.GOOGLE_PLAY_SHA256
        );
        assertEquals(
                "F7A038EB551F1BE8FDF388686B784ABAB4552A5D82DF423E3D8F1B5CBE1C69AE",
                TermuxSignerPolicy.TERMUX_DEVS_SHA256
        );
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
                TermuxSignerPolicy.verifyFingerprint(
                        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                );

        assertFalse(verification.trusted);
        assertNull(verification.source);
        assertNull(verification.fingerprint);
        assertEquals("unrecognized_termux_signer", verification.reason);
    }
}
