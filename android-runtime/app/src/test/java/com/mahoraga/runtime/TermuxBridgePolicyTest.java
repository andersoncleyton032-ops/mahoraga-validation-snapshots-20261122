package com.mahoraga.runtime;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class TermuxBridgePolicyTest {
    @Test
    public void foregroundServiceLaunchIsUsedFromAndroidOAndLater() {
        assertFalse(TermuxBridge.usesForegroundService(25));
        assertTrue(TermuxBridge.usesForegroundService(26));
        assertTrue(TermuxBridge.usesForegroundService(31));
        assertTrue(TermuxBridge.usesForegroundService(36));
    }
}
