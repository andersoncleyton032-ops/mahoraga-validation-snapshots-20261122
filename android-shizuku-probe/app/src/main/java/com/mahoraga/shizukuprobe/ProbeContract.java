package com.mahoraga.shizukuprobe;

public final class ProbeContract {
    public static final int PROTOCOL_VERSION = 1;
    public static final int USER_SERVICE_VERSION = 1;
    public static final int REJECT_INVALID_REQUEST_ID = 1;
    public static final int REJECT_DUPLICATE_REQUEST_ID = 2;
    public static final int REJECT_SERVICE_STOPPING = 3;
    public static final int REJECT_UID_NOT_SHELL = 4;
    public static final int BIND_TIMEOUT_MS = 10_000;
    public static final int OPERATION_TIMEOUT_MS = 5_000;

    private ProbeContract() {}

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