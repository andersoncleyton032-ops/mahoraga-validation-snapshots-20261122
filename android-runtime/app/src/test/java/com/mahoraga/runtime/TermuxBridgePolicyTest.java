package com.mahoraga.runtime;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
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
    public void outputLengthsMustRespectBothStreamsAndCombinedBudget() {
        assertTrue(TermuxBridge.isOutputWithinLimits(1024, 1024));
        assertTrue(TermuxBridge.isOutputWithinLimits(48 * 1024, 16 * 1024));
        assertFalse(TermuxBridge.isOutputWithinLimits(48 * 1024 + 1, 0));
        assertFalse(TermuxBridge.isOutputWithinLimits(0, 16 * 1024 + 1));
        assertFalse(TermuxBridge.isOutputWithinLimits(60 * 1024, 8 * 1024));
        assertFalse(TermuxBridge.isOutputWithinLimits(-1, 0));
    }

    @Test
    public void originalLengthMetadataFailsClosedWhenMalformed() {
        assertEquals(12, TermuxBridge.parseOriginalLength(null, 12));
        assertEquals(120, TermuxBridge.parseOriginalLength("120", 12));
        assertEquals(Integer.MAX_VALUE, TermuxBridge.parseOriginalLength("invalid", 12));
        assertEquals(Integer.MAX_VALUE, TermuxBridge.parseOriginalLength("-1", 12));
    }

    @Test
    public void crossAppForegroundRestrictionRequiresBothAppsToTargetAndroid12() {
        assertFalse(TermuxBridge.requiresCrossAppFgsReview(30, 36, 36));
        assertFalse(TermuxBridge.requiresCrossAppFgsReview(31, 36, 28));
        assertFalse(TermuxBridge.requiresCrossAppFgsReview(31, 28, 36));
        assertTrue(TermuxBridge.requiresCrossAppFgsReview(31, 31, 31));
        assertTrue(TermuxBridge.requiresCrossAppFgsReview(36, 36, 36));
        assertFalse(TermuxBridge.requiresCrossAppFgsReview(36, 36, 28));
    }

    @Test
    public void foregroundServiceLaunchIsUsedFromAndroidOAndLater() {
        assertFalse(TermuxBridge.usesForegroundService(25));
        assertTrue(TermuxBridge.usesForegroundService(26));
        assertTrue(TermuxBridge.usesForegroundService(31));
        assertTrue(TermuxBridge.usesForegroundService(36));
    }

    @Test
    public void resultPendingIntentIdentityIsUniquePerInvocation() {
        String first = TermuxBridge.resultIntentDataUri("00000000-0000-0000-0000-000000000001");
        String second = TermuxBridge.resultIntentDataUri("00000000-0000-0000-0000-000000000002");

        assertEquals("mahoraga://termux-result/00000000-0000-0000-0000-000000000001", first);
        assertNotEquals(first, second);
    }

    @Test(expected = IllegalArgumentException.class)
    public void resultPendingIntentIdentityRejectsBlankRequestId() {
        TermuxBridge.resultIntentDataUri(" ");
    }
}
