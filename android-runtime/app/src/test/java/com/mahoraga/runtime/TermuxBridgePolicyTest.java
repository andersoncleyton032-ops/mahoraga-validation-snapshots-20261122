package com.mahoraga.runtime;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class TermuxBridgePolicyTest {
    @Test
    public void workerCommandHasHardProcessTimeoutAndKillGrace() {
        assertArrayEquals(
                new String[]{
                        "--signal=TERM",
                        "--kill-after=2s",
                        "30s",
                        "/termux/usr/bin/python",
                        "/termux/home/mahoraga/scripts/mahoraga_background_worker.py"
                },
                TermuxBridge.buildTimeoutArguments(
                        "/termux/usr/bin/python",
                        "/termux/home/mahoraga/scripts/mahoraga_background_worker.py"
                )
        );
    }

    @Test
    public void foregroundServiceLaunchIsUsedFromAndroidOAndLater() {
        assertFalse(TermuxBridge.usesForegroundService(25));
        assertTrue(TermuxBridge.usesForegroundService(26));
        assertTrue(TermuxBridge.usesForegroundService(31));
        assertTrue(TermuxBridge.usesForegroundService(36));
    }
}
