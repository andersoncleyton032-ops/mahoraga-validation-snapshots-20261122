package com.mahoraga.shizukuprobe;

import static org.junit.Assert.*;

import org.junit.Test;

public final class ShizukuProbeStateTest {
    @Test
    public void binderUnavailableCannotRequestPermission() {
        ShizukuProbeState state = ShizukuProbeState.binderUnavailable(true);
        assertEquals(ShizukuProbeState.BinderState.UNAVAILABLE, state.getBinderState());
        assertFalse(state.canRequestPermission());
        assertFalse(state.isShellReady());
        assertEquals(-1, state.getUid());
    }

    @Test
    public void binderAvailableAllowsExplicitPermissionRequest() {
        ShizukuProbeState state = ShizukuProbeState.binderAvailable(true);
        assertEquals(ShizukuProbeState.PermissionState.UNKNOWN, state.getPermissionState());
        assertTrue(state.canRequestPermission());
        assertFalse(state.isShellReady());
    }

    @Test
    public void grantedShellIdentityIsReady() {
        ShizukuProbeState state = ShizukuProbeState.permissionGranted(true, 2000);
        assertTrue(state.isShellReady());
        assertFalse(state.isRootRejected());
        assertFalse(state.isOtherIdentityRejected());
        assertFalse(state.canRequestPermission());
    }

    @Test
    public void rootIdentityIsExplicitlyRejected() {
        ShizukuProbeState state = ShizukuProbeState.permissionGranted(true, 0);
        assertFalse(state.isShellReady());
        assertTrue(state.isRootRejected());
    }

    @Test
    public void unexpectedIdentityIsRejected() {
        ShizukuProbeState state = ShizukuProbeState.permissionGranted(true, 1000);
        assertFalse(state.isShellReady());
        assertTrue(state.isOtherIdentityRejected());
    }

    @Test
    public void deniedPermissionWithRationaleCanBeRequestedAgain() {
        ShizukuProbeState state = ShizukuProbeState.permissionDenied(true, true);
        assertEquals(
                ShizukuProbeState.PermissionState.RATIONALE_REQUIRED,
                state.getPermissionState()
        );
        assertTrue(state.canRequestPermission());
        assertFalse(state.isShellReady());
    }

    @Test
    public void binderDeathResetsPermissionAndIdentity() {
        ShizukuProbeState ready = ShizukuProbeState.permissionGranted(true, 2000);
        assertTrue(ready.isShellReady());
        ShizukuProbeState dead = ShizukuProbeState.binderUnavailable(true);
        assertFalse(dead.isShellReady());
        assertEquals(ShizukuProbeState.PermissionState.UNKNOWN, dead.getPermissionState());
        assertEquals(-1, dead.getUid());
    }

    @Test
    public void preV11ServerIsMarkedUnsupported() {
        ShizukuProbeState state = ShizukuProbeState.unsupported(true);
        assertEquals(ShizukuProbeState.BinderState.UNSUPPORTED, state.getBinderState());
        assertFalse(state.canRequestPermission());
        assertFalse(state.isShellReady());
    }
}
