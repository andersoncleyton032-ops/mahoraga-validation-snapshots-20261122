package com.mahoraga.runtime;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import androidx.work.Data;

import org.junit.Test;

public final class MahoragaOneShotWorkerTest {
    @Test
    public void workerEnvelopeRequiresTypedStatusTaskAndBooleans() {
        assertTrue(MahoragaOneShotWorker.isValidWorkerEnvelope(
                "idle", null, false, false
        ));
        assertTrue(MahoragaOneShotWorker.isValidWorkerEnvelope(
                "completed", "task-1", true, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidWorkerEnvelope(
                null, "task-1", true, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidWorkerEnvelope(
                "completed", 42, true, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidWorkerEnvelope(
                "idle", null, "false", false
        ));
        assertFalse(MahoragaOneShotWorker.isValidWorkerEnvelope(
                "idle", null, false, "false"
        ));
    }

    @Test
    public void onlyKnownWorkerStatesWithConsistentReceiptsAreAccepted() {
        assertTrue(MahoragaOneShotWorker.isValidWorkerState("completed", "t1", true, true));
        assertTrue(MahoragaOneShotWorker.isValidWorkerState("completed_reconciled", "t1", false, true));
        assertTrue(MahoragaOneShotWorker.isValidWorkerState("idle", "", false, false));
        assertTrue(MahoragaOneShotWorker.isValidWorkerState("deferred", "t1", false, false));
        assertTrue(MahoragaOneShotWorker.isValidWorkerState("queued", "t1", false, false));
        assertTrue(MahoragaOneShotWorker.isValidWorkerState("failed", "t1", false, false));
        assertFalse(MahoragaOneShotWorker.isValidWorkerState("unknown", "", false, false));
        assertFalse(MahoragaOneShotWorker.isValidWorkerState("completed", "", true, true));
        assertFalse(MahoragaOneShotWorker.isValidWorkerState("idle", "t1", false, false));
        assertFalse(MahoragaOneShotWorker.isValidWorkerState("completed", "t1", false, true));
        assertTrue(MahoragaOneShotWorker.isKnownWorkerStatus("failed"));
        assertFalse(MahoragaOneShotWorker.isKnownWorkerStatus("unknown"));
    }

    @Test
    public void wakeReceiptMustMatchScheduledStatusAndDelay() {
        assertTrue(MahoragaOneShotWorker.isValidWakeReceipt("not_needed", null));
        assertFalse(MahoragaOneShotWorker.isValidWakeReceipt("not_needed", 60));
        assertTrue(MahoragaOneShotWorker.isValidWakeReceipt("scheduled", 60));
        assertTrue(MahoragaOneShotWorker.isValidWakeReceipt("scheduled", 3600));
        assertFalse(MahoragaOneShotWorker.isValidWakeReceipt("scheduled", 59));
        assertFalse(MahoragaOneShotWorker.isValidWakeReceipt("scheduled", 3601));
        assertFalse(MahoragaOneShotWorker.isValidWakeReceipt("scheduled", "60"));
        assertFalse(MahoragaOneShotWorker.isValidWakeReceipt("unknown", null));
    }

    @Test
    public void queueSnapshotMustHaveExactComponentVersionAndTypedCounts() {
        assertTrue(MahoragaOneShotWorker.isValidQueueSnapshot(
                "PersistentBackgroundWorkQueue", "0.1.0",
                1, 2, 3, 4, 5, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidQueueSnapshot(
                "OtherQueue", "0.1.0", 1, 2, 3, 4, 5, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidQueueSnapshot(
                "PersistentBackgroundWorkQueue", "0.2.0", 1, 2, 3, 4, 5, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidQueueSnapshot(
                "PersistentBackgroundWorkQueue", "0.1.0", -1, 2, 3, 4, 5, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidQueueSnapshot(
                "PersistentBackgroundWorkQueue", "0.1.0", 1.5, 2, 3, 4, 5, true
        ));
        assertFalse(MahoragaOneShotWorker.isValidQueueSnapshot(
                "PersistentBackgroundWorkQueue", "0.1.0", 1, 2, 3, 4, 5, "true"
        ));
    }

    @Test
    public void queueSnapshotIsPreservedInWorkManagerOutput() {
        Data output = MahoragaOneShotWorker.buildOutputData(
                "completed",
                "task-17",
                true,
                true,
                "scheduled",
                true,
                17,
                2,
                1,
                3,
                8,
                true
        );

        assertEquals(17, output.getInt("queue_revision", -1));
        assertEquals(2, output.getInt("queue_queued", -1));
        assertEquals(1, output.getInt("queue_claimed", -1));
        assertEquals(3, output.getInt("queue_active_items", -1));
        assertEquals(8, output.getInt("queue_recently_finished", -1));
        assertTrue(output.getBoolean("queue_pending", false));
        assertEquals("task-17", output.getString("task_id"));
        assertTrue(output.getBoolean("completion_receipt_valid", false));
    }

    @Test
    public void missingQueueSnapshotDoesNotInventQueueValues() {
        Data output = MahoragaOneShotWorker.buildOutputData(
                "idle", null, false, false, "not_needed",
                false, -1, -1, -1, -1, -1, false
        );

        assertFalse(output.getKeyValueMap().containsKey("queue_queued"));
        assertFalse(output.getKeyValueMap().containsKey("queue_pending"));
    }
}
