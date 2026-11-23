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

            String status = result.optString("status", "");
            String taskId = result.optString("task_id", "");
            boolean executionPerformed = result.optBoolean("execution_performed", false);
            boolean receiptValid = result.optBoolean("completion_receipt_valid", false);

            JSONObject wake = result.optJSONObject("wake_schedule");
            String wakeStatus = wake == null ? "" : wake.optString("status", "");
            if (!"scheduled".equals(wakeStatus) && !"not_needed".equals(wakeStatus)) {
                return Result.retry();
            }
            if ("completed".equals(status)) {
                if (taskId.isBlank() || !executionPerformed || !receiptValid) {
                    return Result.retry();
                }
            } else if ("completed_reconciled".equals(status)) {
                if (taskId.isBlank() || executionPerformed || !receiptValid) {
                    return Result.retry();
                }
            } else if (executionPerformed || "error".equals(status)) {
                return Result.retry();
            }

            JSONObject queue = result.optJSONObject("queue");
            boolean hasQueue = queue != null;
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
                    hasQueue && queue.optBoolean("pending", false)
            ));
        } catch (JSONException malformed) {
            return Result.retry();
        }
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
