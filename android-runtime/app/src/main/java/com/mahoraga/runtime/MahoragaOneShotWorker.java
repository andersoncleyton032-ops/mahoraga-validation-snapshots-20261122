package com.mahoraga.runtime;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Data;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONException;
import org.json.JSONObject;

public final class MahoragaOneShotWorker extends Worker {
    private static final String RESULT_PREFIX = "MAHORAGA_WORKER_RESULT:";

    public MahoragaOneShotWorker(
            @NonNull Context context,
            @NonNull WorkerParameters workerParameters
    ) {
        super(context, workerParameters);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        if (!WorkScheduler.isEnabled(context)) return Result.success();

        TermuxBridge.ExecutionResult execution = TermuxBridge.executeOnce(context);
        if (!execution.success) {
            Data error = new Data.Builder()
                    .putString("error_code", execution.errorCode)
                    .build();
            return execution.retryable ? Result.retry() : Result.failure(error);
        }

        String payload = extractPayload(execution.stdout);
        if (payload == null) return Result.retry();

        try {
            JSONObject result = new JSONObject(payload);
            if (!"mahoraga.background_worker_result.v1".equals(
                    result.optString("schema")
            )) {
                return Result.failure(new Data.Builder()
                        .putString("error_code", "invalid_worker_result_schema")
                        .build());
            }

            Object taskIdValue = result.isNull("task_id") ? null : result.opt("task_id");
            if (!result.has("task_id") || !isValidWorkerEnvelope(
                    result.opt("status"),
                    taskIdValue,
                    result.opt("execution_performed"),
                    result.opt("completion_receipt_valid")
            )) {
                return Result.failure(new Data.Builder()
                        .putString("error_code", "malformed_worker_result_envelope")
                        .build());
            }
            String status = result.optString("status", "");
            String taskId = result.optString("task_id", "");
            boolean executionPerformed = result.optBoolean("execution_performed", false);
            boolean receiptValid = result.optBoolean("completion_receipt_valid", false);
            if (!isKnownWorkerStatus(status)) {
                return Result.failure(new Data.Builder()
                        .putString("error_code", "unknown_worker_result_status")
                        .build());
            }
            if (!isValidWorkerState(status, taskId, executionPerformed, receiptValid)) {
                return Result.retry();
            }

            JSONObject wake = result.optJSONObject("wake_schedule");
            if (wake == null || !wake.has("status")
                    || !(wake.opt("status") instanceof String)
                    || !wake.has("delay_seconds")) {
                return Result.failure(new Data.Builder()
                        .putString("error_code", "malformed_wake_schedule_envelope")
                        .build());
            }
            String wakeStatus = wake.optString("status", "");
            Object wakeDelay = wake.isNull("delay_seconds") ? null : wake.opt("delay_seconds");
            if (!isValidWakeReceipt(wakeStatus, wakeDelay)) {
                return Result.failure(new Data.Builder()
                        .putString("error_code", "invalid_wake_schedule_receipt")
                        .build());
            }

            JSONObject queue = result.optJSONObject("queue");
            if (queue == null || !isValidQueueSnapshot(
                    queue.optString("component", ""),
                    queue.optString("version", ""),
                    queue.opt("revision"),
                    queue.opt("queued"),
                    queue.opt("claimed"),
                    queue.opt("active_items"),
                    queue.opt("recently_finished"),
                    queue.opt("pending")
            )) {
                return Result.failure(new Data.Builder()
                        .putString("error_code", "invalid_queue_snapshot")
                        .build());
            }
            boolean hasQueue = true;
            boolean queuePending = queue.optBoolean("pending", false);
            if (queuePending != "scheduled".equals(wakeStatus)) {
                return Result.failure(new Data.Builder()
                        .putString("error_code", "queue_wake_receipt_mismatch")
                        .build());
            }
            return Result.success(buildOutputData(
                    status,
                    taskId,
                    executionPerformed,
                    receiptValid,
                    wakeStatus,
                    hasQueue,
                    hasQueue ? queue.optInt("revision", -1) : -1,
                    hasQueue ? queue.optInt("queued", -1) : -1,
                    hasQueue ? queue.optInt("claimed", -1) : -1,
                    hasQueue ? queue.optInt("active_items", -1) : -1,
                    hasQueue ? queue.optInt("recently_finished", -1) : -1,
                    queuePending
            ));
        } catch (JSONException malformed) {
            return Result.retry();
        }
    }



    static boolean isValidWorkerEnvelope(
            Object status, Object taskId, Object executionPerformed, Object receiptValid
    ) {
        return status instanceof String
                && (taskId == null || taskId instanceof String)
                && executionPerformed instanceof Boolean
                && receiptValid instanceof Boolean;
    }

    static boolean isKnownWorkerStatus(String status) {
        return "idle".equals(status)
                || "deferred".equals(status)
                || "queued".equals(status)
                || "failed".equals(status)
                || "completed".equals(status)
                || "completed_reconciled".equals(status);
    }

    static boolean isValidWorkerState(
            String status, String taskId, boolean executionPerformed, boolean receiptValid
    ) {
        if (status == null) return false;
        String safeTaskId = taskId == null ? "" : taskId;
        switch (status) {
            case "completed":
                return !safeTaskId.trim().isEmpty() && executionPerformed && receiptValid;
            case "completed_reconciled":
                return !safeTaskId.trim().isEmpty() && !executionPerformed && receiptValid;
            case "idle":
                return safeTaskId.trim().isEmpty() && !executionPerformed && !receiptValid;
            case "deferred":
            case "queued":
            case "failed":
                return !safeTaskId.trim().isEmpty() && !executionPerformed && !receiptValid;
            default:
                return false;
        }
    }

    static boolean isValidWakeReceipt(String status, Object delaySeconds) {
        if ("not_needed".equals(status)) return delaySeconds == null;
        if (!"scheduled".equals(status) || !(delaySeconds instanceof Number)) return false;
        double value = ((Number) delaySeconds).doubleValue();
        return Double.isFinite(value) && value >= 60 && value <= 3600
                && value == Math.rint(value);
    }

    static boolean isValidQueueSnapshot(
            String component,
            String version,
            Object revision,
            Object queued,
            Object claimed,
            Object activeItems,
            Object recentlyFinished,
            Object pending
    ) {
        return "PersistentBackgroundWorkQueue".equals(component)
                && "0.1.0".equals(version)
                && isNonNegativeInteger(revision)
                && isNonNegativeInteger(queued)
                && isNonNegativeInteger(claimed)
                && isNonNegativeInteger(activeItems)
                && isNonNegativeInteger(recentlyFinished)
                && pending instanceof Boolean;
    }

    private static boolean isNonNegativeInteger(Object value) {
        if (!(value instanceof Number)) return false;
        double number = ((Number) value).doubleValue();
        return Double.isFinite(number) && number >= 0
                && number <= Integer.MAX_VALUE && number == Math.rint(number);
    }

    static Data buildOutputData(
            String status,
            String taskId,
            boolean executionPerformed,
            boolean receiptValid,
            String wakeStatus,
            boolean hasQueueSnapshot,
            int queueRevision,
            int queueQueued,
            int queueClaimed,
            int queueActiveItems,
            int queueRecentlyFinished,
            boolean queuePending
    ) {
        Data.Builder output = new Data.Builder()
                .putString("status", status)
                .putString("task_id", taskId)
                .putBoolean("execution_performed", executionPerformed)
                .putBoolean("completion_receipt_valid", receiptValid)
                .putString("wake_status", wakeStatus);
        if (hasQueueSnapshot) {
            output.putInt("queue_revision", queueRevision)
                    .putInt("queue_queued", queueQueued)
                    .putInt("queue_claimed", queueClaimed)
                    .putInt("queue_active_items", queueActiveItems)
                    .putInt("queue_recently_finished", queueRecentlyFinished)
                    .putBoolean("queue_pending", queuePending);
        }
        return output.build();
    }

    private static String extractPayload(String stdout) {
        if (stdout == null || stdout.isEmpty()) return null;
        int marker = stdout.lastIndexOf(RESULT_PREFIX);
        if (marker < 0) return null;
        String value = stdout.substring(marker + RESULT_PREFIX.length());
        int newline = value.indexOf('\n');
        if (newline >= 0) value = value.substring(0, newline);
        value = value.trim();
        return value.isEmpty() ? null : value;
    }
}
