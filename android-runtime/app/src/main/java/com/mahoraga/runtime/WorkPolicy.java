package com.mahoraga.runtime;

public final class WorkPolicy {
    public static final int MIN_NEXT_DELAY_SECONDS = 60;
    public static final int MAX_NEXT_DELAY_SECONDS = 3600;
    public static final int POLL_INTERVAL_MINUTES = 15;
    // Python queue claims use a 90-second lease; retries must wait beyond lease expiry.
    public static final int RETRY_BACKOFF_SECONDS = 120;
    public static final long RECEIVER_RATE_LIMIT_MS = 30_000L;
    public static final String TRUSTED_WAKE_SENDER_PACKAGE = "com.termux";

    private WorkPolicy() {}

    public static boolean isTrustedWakeSender(int sdkInt, String senderPackage) {
        // Android 14+ exposes original sender identity; older releases retain the rate-limited compatibility path.
        return sdkInt < 34 || TRUSTED_WAKE_SENDER_PACKAGE.equals(senderPackage);
    }

    public static boolean isValidNextDelay(int seconds) {
        return seconds >= MIN_NEXT_DELAY_SECONDS
                && seconds <= MAX_NEXT_DELAY_SECONDS;
    }

    public static boolean isValidInitialDelay(int seconds) {
        return seconds >= 0 && seconds <= MAX_NEXT_DELAY_SECONDS;
    }
}
