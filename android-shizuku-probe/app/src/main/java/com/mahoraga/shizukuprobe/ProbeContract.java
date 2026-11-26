package com.mahoraga.shizukuprobe;

import java.util.UUID;

public final class ProbeContract {
    public static final int PROTOCOL_VERSION = 1;
    public static final int USER_SERVICE_VERSION = 1;
    public static final int REJECT_INVALID_REQUEST_ID = 1;
    public static final int REJECT_DUPLICATE_REQUEST_ID = 2;
    public static final int REJECT_SERVICE_STOPPING = 3;
    public static final int REJECT_UID_NOT_SHELL = 4;
    public static final int BIND_TIMEOUT_MS = 10_000;
    public static final int HANDSHAKE_TIMEOUT_MS = 5_000;
    public static final int OPERATION_TIMEOUT_MS = 5_000;
    private static final String PROCESS_INSTANCE_ID =
            UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    private static final String USER_SERVICE_TAG_PREFIX =
            "mahoraga.shizuku.probe.alpha2.p" + PROCESS_INSTANCE_ID + ".g";
    private static final String USER_SERVICE_PROCESS_PREFIX =
            "mahoraga_probe_p" + PROCESS_INSTANCE_ID + "_g";

    private ProbeContract() {}

    public static String userServiceTag(long generation) {
        if (generation <= 0) throw new IllegalArgumentException("generation must be positive");
        return USER_SERVICE_TAG_PREFIX + generation;
    }

    public static String userServiceProcessSuffix(long generation) {
        if (generation <= 0) throw new IllegalArgumentException("generation must be positive");
        return USER_SERVICE_PROCESS_PREFIX + generation;
    }

    public static boolean isValidRequestId(String value) {
        if (value == null || value.length() != 36) return false;
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (i == 8 || i == 13 || i == 18 || i == 23) {
                if (c != '-') return false;
            } else if (!((c >= '0' && c <= '9')
                    || (c >= 'a' && c <= 'f')
                    || (c >= 'A' && c <= 'F'))) {
                return false;
            }
        }
        return true;
    }
}
