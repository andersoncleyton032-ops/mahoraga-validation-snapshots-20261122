package com.mahoraga.runtime;

import androidx.work.Constraints;
import androidx.work.NetworkType;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class WorkPolicyTest {
    @Test
    public void acceptsOnlyBoundedNextWakeDelays() {
        assertTrue(WorkPolicy.isValidNextDelay(60));
        assertTrue(WorkPolicy.isValidNextDelay(900));
        assertTrue(WorkPolicy.isValidNextDelay(3600));
        assertFalse(WorkPolicy.isValidNextDelay(0));
        assertFalse(WorkPolicy.isValidNextDelay(59));
        assertFalse(WorkPolicy.isValidNextDelay(3601));
    }

    @Test
    public void allowsImmediateOnlyForExplicitInitialSchedule() {
        assertTrue(WorkPolicy.isValidInitialDelay(0));
        assertTrue(WorkPolicy.isValidInitialDelay(60));
        assertFalse(WorkPolicy.isValidInitialDelay(-1));
        assertFalse(WorkPolicy.isValidInitialDelay(3601));
    }

    @Test
    public void retryBackoffExceedsPythonQueueLease() {
        assertTrue(WorkPolicy.RETRY_BACKOFF_SECONDS > 90);
    }

    @Test
    public void wakeSenderMustBeVerifiableAndMatchTermuxUid() {
        assertFalse(WorkPolicy.isTrustedWakeSender(24, 10456, 10456));
        assertFalse(WorkPolicy.isTrustedWakeSender(33, 10456, 10456));
        assertTrue(WorkPolicy.isTrustedWakeSender(34, 10456, 10456));
        assertTrue(WorkPolicy.isTrustedWakeSender(36, 10456, 10456));
        assertFalse(WorkPolicy.isTrustedWakeSender(34, 10457, 10456));
        assertFalse(WorkPolicy.isTrustedWakeSender(36, -1, 10456));
        assertFalse(WorkPolicy.isTrustedWakeSender(36, 10456, -1));
    }

    @Test
    public void resourceHeadroomIsGovernedDynamicallyRatherThanByHardWorkManagerGates() {
        Constraints constraints = WorkScheduler.buildConstraints();

        assertEquals(NetworkType.NOT_REQUIRED, constraints.getRequiredNetworkType());
        assertFalse(constraints.requiresCharging());
        assertFalse(constraints.requiresBatteryNotLow());
        assertFalse(constraints.requiresStorageNotLow());
    }
}
