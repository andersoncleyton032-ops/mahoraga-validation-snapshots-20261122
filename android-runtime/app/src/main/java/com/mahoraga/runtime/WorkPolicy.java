package com.mahoraga.runtime;

public final class WorkPolicy {
    public static final int MIN_NEXT_DELAY_SECONDS = 60;
    public static final int MAX_NEXT_DELAY_SECONDS = 3600;
    public static final int POLL_INTERVAL_MINUTES = 15;
    // Python queue claims use a 90-second lease; retries must wait beyond lease expiry.
    public static final int RETRY_BACKOFF_SECONDS = 120;
    public static final long RECEIVER_RATE_LIMIT_MS = 30_000L;

    private WorkPolicy() {}

    public static boolean supportsAuthenticatedWake(int sdkInt) {
        return sdkInt >= 34;
    }

    public static boolean isTrustedWakeSender(int sdkInt, int senderUid, int termuxUid) {
        // Android 14+ exposes the sender UID. Older releases cannot authenticate
        // this exported wake receiver, so background execution is disabled there.
        return supportsAuthenticatedWake(sdkInt)
                && termuxUid >= 0
                && senderUid == termuxUid;
    }

    public static boolean isValidNextDelay(int seconds) {
        return seconds >= MIN_NEXT_DELAY_SECONDS
                && seconds <= MAX_NEXT_DELAY_SECONDS;
    }

    public static boolean isValidInitialDelay(int seconds) {
        return seconds >= 0 && seconds <= MAX_NEXT_DELAY_SECONDS;
    }
}
