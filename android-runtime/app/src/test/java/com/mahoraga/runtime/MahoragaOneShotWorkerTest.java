package com.mahoraga.runtime;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import androidx.work.Data;

import org.junit.Test;

public final class MahoragaOneShotWorkerTest {
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
