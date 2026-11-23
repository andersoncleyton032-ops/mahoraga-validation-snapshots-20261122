package com.mahoraga.runtime;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;

import java.io.File;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

public final class TermuxBridge {
    public static final String TERMUX_PACKAGE = "com.termux";
    public static final String RUN_COMMAND_PERMISSION =
            "com.termux.permission.RUN_COMMAND";
    private static final String ACTION_RUN_COMMAND = "com.termux.RUN_COMMAND";
    private static final String RUN_COMMAND_SERVICE =
            "com.termux.app.RunCommandService";
    private static final String EXTRA_COMMAND_PATH =
            "com.termux.RUN_COMMAND_PATH";
    private static final String EXTRA_ARGUMENTS =
            "com.termux.RUN_COMMAND_ARGUMENTS";
    private static final String EXTRA_WORKDIR =
            "com.termux.RUN_COMMAND_WORKDIR";
    private static final String EXTRA_BACKGROUND =
            "com.termux.RUN_COMMAND_BACKGROUND";
    private static final String EXTRA_PENDING_INTENT =
            "com.termux.RUN_COMMAND_PENDING_INTENT";
    private static final String EXTRA_COMMAND_LABEL =
            "com.termux.RUN_COMMAND_COMMAND_LABEL";
    private static final String EXTRA_COMMAND_DESCRIPTION =
            "com.termux.RUN_COMMAND_COMMAND_DESCRIPTION";

    private static final String RESULT_STDOUT = "stdout";
    private static final String RESULT_STDOUT_ORIGINAL_LENGTH = "stdout_original_length";
    private static final String RESULT_STDERR = "stderr";
    private static final String RESULT_STDERR_ORIGINAL_LENGTH = "stderr_original_length";
    private static final String RESULT_EXIT_CODE = "exitCode";
    private static final String RESULT_ERR = "err";
    private static final String RESULT_ERRMSG = "errmsg";
    private static final long RESULT_TIMEOUT_SECONDS = 45L;
    private static final int COMMAND_TIMEOUT_SECONDS = 30;
    private static final int COMMAND_KILL_GRACE_SECONDS = 2;
    private static final int MAX_STDOUT_CHARS = 48 * 1024;
    private static final int MAX_STDERR_CHARS = 16 * 1024;
    private static final int MAX_TOTAL_OUTPUT_CHARS = 64 * 1024;

    private TermuxBridge() {}

    public static boolean isInstalled(Context context) {
        try {
            context.getPackageManager().getPackageInfo(TERMUX_PACKAGE, 0);
            return true;
        } catch (PackageManager.NameNotFoundException missing) {
            return false;
        }
    }

    public static boolean hasRunCommandPermission(Context context) {
        return context.checkSelfPermission(RUN_COMMAND_PERMISSION)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static ExecutionResult executeOnce(Context context) {
        Context app = context.getApplicationContext();
        if (!isInstalled(app)) {
            return ExecutionResult.failure("termux_not_installed", false);
        }
        if (!hasRunCommandPermission(app)) {
            return ExecutionResult.failure("termux_run_command_permission_missing", false);
        }

        PackageManager packageManager = app.getPackageManager();
        final ApplicationInfo termuxInfo;
        final PackageInfo termuxPackage;
        try {
            termuxInfo = packageManager.getApplicationInfo(TERMUX_PACKAGE, 0);
            termuxPackage = packageManager.getPackageInfo(TERMUX_PACKAGE, 0);
        } catch (PackageManager.NameNotFoundException missing) {
            return ExecutionResult.failure("termux_not_installed", false);
        }
        if (!supportsResultPendingIntent(termuxPackage.versionName)) {
            return ExecutionResult.failure("termux_version_requires_0_109_or_newer", false);
        }

        String termuxHome = new File(termuxInfo.dataDir, "files/home").getAbsolutePath();
        String projectRoot = new File(termuxHome, "mahoraga").getAbsolutePath();
        String scriptPath = new File(
                new File(projectRoot, "scripts"),
                "mahoraga_background_worker.py"
        ).getAbsolutePath();
        File termuxBin = new File(termuxInfo.dataDir, "files/usr/bin");
        String pythonPath = new File(termuxBin, "python").getAbsolutePath();
        String timeoutPath = new File(termuxBin, "timeout").getAbsolutePath();
        File timeoutExecutable = new File(timeoutPath);
        if (!timeoutExecutable.isFile() || !timeoutExecutable.canExecute()) {
            return ExecutionResult.failure("termux_timeout_utility_missing", false);
        }

        String requestId = UUID.randomUUID().toString();
        CompletableFuture<Bundle> future;
        try {
            future = TermuxResultReceiver.register(requestId);
        } catch (RuntimeException duplicate) {
            return ExecutionResult.failure("termux_result_registration_failed", true);
        }

        int requestCode = (requestId.hashCode() & 0x7fffffff);
        Intent resultIntent = new Intent(app, TermuxResultReceiver.class)
                .setAction(TermuxResultReceiver.ACTION_RESULT)
                .putExtra(TermuxResultReceiver.EXTRA_REQUEST_ID, requestId);

        int pendingFlags = PendingIntent.FLAG_ONE_SHOT | PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            pendingFlags |= PendingIntent.FLAG_MUTABLE;
        }
        PendingIntent resultPendingIntent = PendingIntent.getBroadcast(
                app, requestCode, resultIntent, pendingFlags
        );

        Intent command = new Intent(ACTION_RUN_COMMAND)
                .setClassName(TERMUX_PACKAGE, RUN_COMMAND_SERVICE)
                .putExtra(EXTRA_COMMAND_PATH, timeoutPath)
                .putExtra(EXTRA_ARGUMENTS, buildTimeoutArguments(pythonPath, scriptPath))
                .putExtra(EXTRA_WORKDIR, projectRoot)
                .putExtra(EXTRA_BACKGROUND, true)
                .putExtra(EXTRA_PENDING_INTENT, resultPendingIntent)
                .putExtra(EXTRA_COMMAND_LABEL, "Mahoraga bounded background task")
                .putExtra(
                        EXTRA_COMMAND_DESCRIPTION,
                        "One local checkpointable task. No network access."
                );

        try {
            startTermuxCommand(app, command);
            Bundle result = TermuxResultReceiver.await(
                    requestId, future, RESULT_TIMEOUT_SECONDS
            );
            if (result == null) {
                return ExecutionResult.failure("termux_result_timeout", true);
            }

            int internalError = result.getInt(RESULT_ERR, Activity.RESULT_CANCELED);
            if (internalError != Activity.RESULT_OK) {
                String error = result.getString(RESULT_ERRMSG, "termux_command_rejected");
                return ExecutionResult.failure(safeError(error), false);
            }

            int exitCode = result.getInt(RESULT_EXIT_CODE, -1);
            String stdout = result.getString(RESULT_STDOUT, "");
            String stderr = result.getString(RESULT_STDERR, "");
            int stdoutOriginalLength = parseOriginalLength(
                    result.getString(RESULT_STDOUT_ORIGINAL_LENGTH), stdout.length()
            );
            int stderrOriginalLength = parseOriginalLength(
                    result.getString(RESULT_STDERR_ORIGINAL_LENGTH), stderr.length()
            );
            if (!isOutputWithinLimits(stdoutOriginalLength, stderrOriginalLength)) {
                return ExecutionResult.failure("termux_result_exceeded_output_limit", false);
            }
            if (exitCode != 0) {
                return ExecutionResult.failure("termux_worker_exit_" + exitCode, true);
            }
            return ExecutionResult.success(stdout);
        } catch (SecurityException denied) {
            return ExecutionResult.failure("termux_run_command_denied", false);
        } catch (RuntimeException startFailure) {
            return ExecutionResult.failure("termux_service_start_failed", true);
        } catch (Exception waitFailure) {
            return ExecutionResult.failure("termux_result_wait_failed", true);
        } finally {
            resultPendingIntent.cancel();
            TermuxResultReceiver.cancel(requestId, future);
        }
    }



    static String[] buildTimeoutArguments(String pythonPath, String scriptPath) {
        return new String[]{
                "--signal=TERM",
                "--kill-after=" + COMMAND_KILL_GRACE_SECONDS + "s",
                COMMAND_TIMEOUT_SECONDS + "s",
                pythonPath,
                scriptPath
        };
    }

    static boolean usesForegroundService(int sdkInt) {
        return sdkInt >= Build.VERSION_CODES.O;
    }

    static void startTermuxCommand(Context context, Intent command) {
        if (usesForegroundService(Build.VERSION.SDK_INT)) {
            context.startForegroundService(command);
        } else {
            context.startService(command);
        }
    }

    private static boolean supportsResultPendingIntent(String versionName) {
        if (versionName == null) return false;
        String[] parts = versionName.split("\\.");
        if (parts.length < 2) return false;
        try {
            int major = Integer.parseInt(parts[0]);
            int minor = Integer.parseInt(parts[1]);
            return major > 0 || (major == 0 && minor >= 109);
        } catch (NumberFormatException invalid) {
            return false;
        }
    }

    static boolean isOutputWithinLimits(int stdoutLength, int stderrLength) {
        return stdoutLength >= 0
                && stderrLength >= 0
                && stdoutLength <= MAX_STDOUT_CHARS
                && stderrLength <= MAX_STDERR_CHARS
                && (long) stdoutLength + (long) stderrLength <= MAX_TOTAL_OUTPUT_CHARS;
    }

    static int parseOriginalLength(String value, int fallback) {
        if (value == null) return fallback;
        try {
            int parsed = Integer.parseInt(value);
            return parsed < 0 ? Integer.MAX_VALUE : parsed;
        } catch (NumberFormatException invalid) {
            return Integer.MAX_VALUE;
        }
    }

    private static String safeError(String value) {
        if (value == null || value.trim().isEmpty()) return "termux_command_rejected";
        String normalized = value.replaceAll("[\\r\\n\\t]", " ").trim();
        return normalized.substring(0, Math.min(normalized.length(), 120));
    }

    public static final class ExecutionResult {
        public final boolean success;
        public final boolean retryable;
        public final String stdout;
        public final String errorCode;

        private ExecutionResult(
                boolean success, boolean retryable, String stdout, String errorCode
        ) {
            this.success = success;
            this.retryable = retryable;
            this.stdout = stdout;
            this.errorCode = errorCode;
        }

        public static ExecutionResult success(String stdout) {
            return new ExecutionResult(true, false, stdout, null);
        }

        public static ExecutionResult failure(String code, boolean retryable) {
            return new ExecutionResult(false, retryable, "", code);
        }
    }
}
