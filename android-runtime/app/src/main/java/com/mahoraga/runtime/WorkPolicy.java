package com.mahoraga.runtime;

public final class WorkPolicy {
    public static final int MIN_NEXT_DELAY_SECONDS = 60;
    public static final int MAX_NEXT_DELAY_SECONDS = 3600;
    public static final int POLL_INTERVAL_MINUTES = 15;
    public static final long RECEIVER_RATE_LIMIT_MS = 30_000L;

    private WorkPolicy() {}

    public static boolean isValidNextDelay(int seconds) {
        return seconds >= MIN_NEXT_DELAY_SECONDS
                && seconds <= MAX_NEXT_DELAY_SECONDS;
    }

    public static boolean isValidInitialDelay(int seconds) {
        return seconds >= 0 && seconds <= MAX_NEXT_DELAY_SECONDS;
    }
}
