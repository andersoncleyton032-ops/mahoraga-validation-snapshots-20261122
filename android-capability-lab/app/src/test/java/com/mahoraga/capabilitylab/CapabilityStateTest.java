package com.mahoraga.capabilitylab;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public final class CapabilityStateTest {
    @Test
    public void absentFeatureIsUnsupportedEvenWhenPermissionIsGranted() {
        assertEquals(
                CapabilityState.Status.UNSUPPORTED,
                CapabilityState.permission(false, true)
        );
    }

    @Test
    public void presentFeatureWithoutPermissionRequiresPermission() {
        assertEquals(
                CapabilityState.Status.REQUIRES_PERMISSION,
                CapabilityState.permission(true, false)
        );
    }

    @Test
    public void presentFeatureWithPermissionIsAvailable() {
        assertEquals(
                CapabilityState.Status.AVAILABLE,
                CapabilityState.permission(true, true)
        );
    }

    @Test
    public void absentOptionalPackageIsNotMisclassifiedAsUnsupported() {
        assertEquals(
                CapabilityState.Status.TEMPORARILY_UNAVAILABLE,
                CapabilityState.optionalPackage(false)
        );
    }
}
