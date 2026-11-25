package com.mahoraga.capabilitylab;

public final class CapabilityState {
    public enum Status {
        AVAILABLE,
        REQUIRES_PERMISSION,
        REQUIRES_USER_ACTION,
        TEMPORARILY_UNAVAILABLE,
        UNSUPPORTED,
        FAILED
    }

    private CapabilityState() {}

    public static Status permission(boolean featurePresent, boolean granted) {
        if (!featurePresent) return Status.UNSUPPORTED;
        return granted ? Status.AVAILABLE : Status.REQUIRES_PERMISSION;
    }

    public static Status optionalFeature(boolean present) {
        return present ? Status.AVAILABLE : Status.UNSUPPORTED;
    }

    public static Status optionalPackage(boolean installed) {
        return installed ? Status.AVAILABLE : Status.TEMPORARILY_UNAVAILABLE;
    }
}
