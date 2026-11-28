package com.mahoraga.capabilitylab;

public final class CapabilityState {
    public enum Status {
        AVAILABLE,
        REQUIRES_PERMISSION,
        REQUIRES_USER_ACTION,
        BLOCKED_BY_MANIFEST,
        TEMPORARILY_UNAVAILABLE,
        UNSUPPORTED,
        FAILED
    }

    private CapabilityState() {}

    public static Status permission(boolean featurePresent, boolean granted) {
        return permission(featurePresent, true, granted);
    }

    public static Status permission(boolean featurePresent, boolean permissionDeclared, boolean granted) {
        if (!featurePresent) return Status.UNSUPPORTED;
        if (!permissionDeclared) return Status.BLOCKED_BY_MANIFEST;
        return granted ? Status.AVAILABLE : Status.REQUIRES_PERMISSION;
    }

    public static Status optionalFeature(boolean present) {
        return present ? Status.AVAILABLE : Status.UNSUPPORTED;
    }

    public static Status optionalPackage(boolean installed) {
        return installed ? Status.AVAILABLE : Status.TEMPORARILY_UNAVAILABLE;
    }
}
