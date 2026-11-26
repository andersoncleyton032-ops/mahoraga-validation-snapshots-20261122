package com.mahoraga.shizukuprobe;

public final class ShizukuProbeState {
    public enum BinderState {
        UNAVAILABLE,
        AVAILABLE,
        UNSUPPORTED
    }

    public enum PermissionState {
        UNKNOWN,
        GRANTED,
        DENIED,
        RATIONALE_REQUIRED
    }

    private final boolean shizukuInstalled;
    private final BinderState binderState;
    private final PermissionState permissionState;
    private final int uid;

    private ShizukuProbeState(
            boolean shizukuInstalled,
            BinderState binderState,
            PermissionState permissionState,
            int uid
    ) {
        this.shizukuInstalled = shizukuInstalled;
        this.binderState = binderState;
        this.permissionState = permissionState;
        this.uid = uid;
    }

    public static ShizukuProbeState binderUnavailable(boolean installed) {
        return new ShizukuProbeState(
                installed, BinderState.UNAVAILABLE, PermissionState.UNKNOWN, -1
        );
    }

    public static ShizukuProbeState binderAvailable(boolean installed) {
        return new ShizukuProbeState(
                installed, BinderState.AVAILABLE, PermissionState.UNKNOWN, -1
        );
    }

    public static ShizukuProbeState unsupported(boolean installed) {
        return new ShizukuProbeState(
                installed, BinderState.UNSUPPORTED, PermissionState.UNKNOWN, -1
        );
    }

    public static ShizukuProbeState permissionDenied(boolean installed, boolean rationale) {
        return new ShizukuProbeState(
                installed,
                BinderState.AVAILABLE,
                rationale ? PermissionState.RATIONALE_REQUIRED : PermissionState.DENIED,
                -1
        );
    }

    public static ShizukuProbeState permissionGranted(boolean installed, int uid) {
        return new ShizukuProbeState(
                installed, BinderState.AVAILABLE, PermissionState.GRANTED, uid
        );
    }

    public boolean isShizukuInstalled() {
        return shizukuInstalled;
    }

    public BinderState getBinderState() {
        return binderState;
    }

    public PermissionState getPermissionState() {
        return permissionState;
    }

    public int getUid() {
        return uid;
    }

    public boolean canRequestPermission() {
        return binderState == BinderState.AVAILABLE
                && permissionState != PermissionState.GRANTED;
    }

    public boolean isShellReady() {
        return binderState == BinderState.AVAILABLE
                && permissionState == PermissionState.GRANTED
                && uid == 2000;
    }

    public boolean isRootRejected() {
        return binderState == BinderState.AVAILABLE
                && permissionState == PermissionState.GRANTED
                && uid == 0;
    }

    public boolean isOtherIdentityRejected() {
        return binderState == BinderState.AVAILABLE
                && permissionState == PermissionState.GRANTED
                && uid != 0
                && uid != 2000;
    }
}
