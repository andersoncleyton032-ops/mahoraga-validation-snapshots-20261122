package com.mahoraga.runtime;

import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;

/** Source-aware allowlist for official Termux release signing certificates. */
public final class TermuxSignerPolicy {
    public static final String FDROID_SHA256 =
            "228FB2CFE90831C1499EC3CCAF61E96E8E1CE70766B9474672CE427334D41C42";
    public static final String GITHUB_SHA256 =
            "B6DA01480EEFD5FBF2CD3771B8D1021EC791304BDD6C4BF41D3FAABAD48EE5E1";
    public static final String GOOGLE_PLAY_SHA256 =
            "738F0A30A04D3C8A1BE304AF18D0779BCF3EA88FB60808F657A3521861C2EBF9";
    public static final String TERMUX_DEVS_SHA256 =
            "F7A038EB551F1BE8FDF388686B784ABAB4552A5D82DF423E3D8F1B5CBE1C69AE";

    private static final char[] HEX = "0123456789ABCDEF".toCharArray();

    private TermuxSignerPolicy() {}

    public static int packageInfoFlags(int sdkInt) {
        return sdkInt >= 28
                ? PackageManager.GET_SIGNING_CERTIFICATES
                : PackageManager.GET_SIGNATURES;
    }

    public static Verification verify(PackageInfo packageInfo, int sdkInt) {
        if (packageInfo == null) {
            return Verification.rejected("package_info_missing");
        }
        Signature signer = sdkInt >= 28
                ? Api28.currentSigner(packageInfo)
                : Legacy.currentSigner(packageInfo);
        if (signer == null) {
            return Verification.rejected("current_signer_unavailable_or_ambiguous");
        }
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(signer.toByteArray());
            return verifyFingerprint(toHex(digest));
        } catch (NoSuchAlgorithmException unavailable) {
            return Verification.rejected("sha256_unavailable");
        }
    }

    public static Verification verifyFingerprint(String fingerprint) {
        String normalized = normalizeFingerprint(fingerprint);
        if (normalized == null) {
            return Verification.rejected("invalid_signer_fingerprint");
        }
        String source = sourceForNormalizedFingerprint(normalized);
        if (source == null) {
            return Verification.rejected("unrecognized_termux_signer");
        }
        return Verification.accepted(source, normalized);
    }

    public static String sourceForFingerprint(String fingerprint) {
        String normalized = normalizeFingerprint(fingerprint);
        return normalized == null ? null : sourceForNormalizedFingerprint(normalized);
    }

    public static String normalizeFingerprint(String fingerprint) {
        if (fingerprint == null) return null;
        String normalized = fingerprint
                .replace(":", "")
                .replaceAll("\\s+", "")
                .toUpperCase(Locale.ROOT);
        if (normalized.length() != 64) return null;
        for (int index = 0; index < normalized.length(); index++) {
            char value = normalized.charAt(index);
            if (!((value >= '0' && value <= '9')
                    || (value >= 'A' && value <= 'F'))) {
                return null;
            }
        }
        return normalized;
    }

    private static String sourceForNormalizedFingerprint(String fingerprint) {
        if (FDROID_SHA256.equals(fingerprint)) return "F-Droid";
        if (GITHUB_SHA256.equals(fingerprint)) return "GitHub release";
        if (GOOGLE_PLAY_SHA256.equals(fingerprint)) return "Google Play";
        if (TERMUX_DEVS_SHA256.equals(fingerprint)) return "Termux Devs";
        return null;
    }

    private static String toHex(byte[] bytes) {
        StringBuilder output = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            int unsigned = value & 0xff;
            output.append(HEX[(unsigned >>> 4) & 0x0f]);
            output.append(HEX[unsigned & 0x0f]);
        }
        return output.toString();
    }

    private static final class Api28 {
        private static Signature currentSigner(PackageInfo packageInfo) {
            if (packageInfo.signingInfo == null
                    || packageInfo.signingInfo.hasMultipleSigners()) {
                return null;
            }
            Signature[] history = packageInfo.signingInfo.getSigningCertificateHistory();
            if (history == null || history.length == 0) return null;
            // Android returns the current signer as the last item in the verified lineage.
            return history[history.length - 1];
        }
    }

    @SuppressWarnings("deprecation")
    private static final class Legacy {
        private static Signature currentSigner(PackageInfo packageInfo) {
            if (packageInfo.signatures == null || packageInfo.signatures.length != 1) {
                return null;
            }
            return packageInfo.signatures[0];
        }
    }

    public static final class Verification {
        public final boolean trusted;
        public final String source;
        public final String fingerprint;
        public final String reason;

        private Verification(
                boolean trusted, String source, String fingerprint, String reason
        ) {
            this.trusted = trusted;
            this.source = source;
            this.fingerprint = fingerprint;
            this.reason = reason;
        }

        public static Verification accepted(String source, String fingerprint) {
            return new Verification(true, source, fingerprint, null);
        }

        public static Verification rejected(String reason) {
            return new Verification(false, null, null, reason);
        }
    }
}
