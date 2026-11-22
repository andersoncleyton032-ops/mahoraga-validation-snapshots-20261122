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

            JSONObject wake = result.optJSONObject("wake_schedule");
            String wakeStatus = wake == null ? "" : wake.optString("status", "");
            if ("adapter_error".equals(wakeStatus)
                    || "adapter_rejected".equals(wakeStatus)
                    || "adapter_missing".equals(wakeStatus)
                    || "invalid_delay".equals(wakeStatus)
                    || "invalid_schedule_receipt".equals(wakeStatus)) {
                return Result.retry();
            }
            if ("error".equals(result.optString("status"))) return Result.retry();

            Data output = new Data.Builder()
                    .putString("status", result.optString("status", "unknown"))
                    .putString("task_id", result.optString("task_id", ""))
                    .build();
            return Result.success(output);
        } catch (JSONException malformed) {
            return Result.retry();
        }
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
