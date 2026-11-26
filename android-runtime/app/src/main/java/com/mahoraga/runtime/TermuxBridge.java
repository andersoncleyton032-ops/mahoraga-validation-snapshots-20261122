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
import android.net.Uri;

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

    public static TermuxSignerPolicy.Verification verifyInstalledSigner(Context context) {
        Context app = context.getApplicationContext();
        PackageManager packageManager = app.getPackageManager();
        try {
            PackageInfo termuxPackage = packageManager.getPackageInfo(
                    TERMUX_PACKAGE,
                    TermuxSignerPolicy.packageInfoFlags(Build.VERSION.SDK_INT)
            );
            return TermuxSignerPolicy.verify(termuxPackage, Build.VERSION.SDK_INT);
        } catch (PackageManager.NameNotFoundException missing) {
            return TermuxSignerPolicy.Verification.rejected("termux_not_installed");
        } catch (RuntimeException inspectionFailure) {
            return TermuxSignerPolicy.Verification.rejected("termux_signer_inspection_failed");
        }
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
            termuxPackage = packageManager.getPackageInfo(
                    TERMUX_PACKAGE,
                    TermuxSignerPolicy.packageInfoFlags(Build.VERSION.SDK_INT)
            );
        } catch (PackageManager.NameNotFoundException missing) {
            return ExecutionResult.failure("termux_not_installed", false);
        } catch (RuntimeException inspectionFailure) {
            return ExecutionResult.failure("termux_signer_inspection_failed", false);
        }
        TermuxSignerPolicy.Verification signer =
                TermuxSignerPolicy.verify(termuxPackage, Build.VERSION.SDK_INT);
        if (!signer.trusted) {
            return ExecutionResult.failure("termux_signer_untrusted", false);
        }
        if (requiresCrossAppFgsReview(
                Build.VERSION.SDK_INT,
                app.getApplicationInfo().targetSdkVersion,
                termuxInfo.targetSdkVersion
        )) {
            return ExecutionResult.failure(
                    "termux_target_sdk_requires_background_fgs_review", false
            );
        }
        if (!supportsResultPendingIntent(termuxPackage.versionName)) {
            return ExecutionResult.failure("termux_version_requires_0_109_or_newer", false);
        }

        // These paths belong to Termux's private app sandbox. Mahoraga may
        // pass the path strings to Termux RUN_COMMAND, but must not stat or
        // access the files directly from its own UID.
        String termuxHome = termuxInfo.dataDir + "/files/home";
        String projectRoot = termuxHome + "/mahoraga";
        String scriptPath = projectRoot + "/scripts/mahoraga_background_worker.py";
        String termuxBin = termuxInfo.dataDir + "/files/usr/bin";
        String pythonPath = termuxBin + "/python";
        String timeoutPath = termuxBin + "/timeout";

        String requestId = UUID.randomUUID().toString();
        CompletableFuture<Bundle> future;
        try {
            future = TermuxResultReceiver.register(requestId);
        } catch (RuntimeException duplicate) {
            return ExecutionResult.failure("termux_result_registration_failed", true);
        }

        PendingIntent resultPendingIntent = null;
        try {
            int requestCode = (requestId.hashCode() & 0x7fffffff);
            Intent resultIntent = new Intent(app, TermuxResultReceiver.class)
                    .setAction(TermuxResultReceiver.ACTION_RESULT)
                    .setData(Uri.parse(resultIntentDataUri(requestId)))
                    .putExtra(TermuxResultReceiver.EXTRA_REQUEST_ID, requestId);

            int pendingFlags = PendingIntent.FLAG_ONE_SHOT | PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                pendingFlags |= PendingIntent.FLAG_MUTABLE;
            }
            resultPendingIntent = PendingIntent.getBroadcast(
                    app, requestCode, resultIntent, pendingFlags
            );
            if (resultPendingIntent == null) {
                return ExecutionResult.failure("termux_result_pending_intent_unavailable", false);
            }

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
                            "One local checkpointable task. This worker does not request network tools."
                    );

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
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return ExecutionResult.failure("termux_result_wait_interrupted", true);
        } catch (Exception waitFailure) {
            return ExecutionResult.failure("termux_result_wait_failed", true);
        } finally {
            if (resultPendingIntent != null) resultPendingIntent.cancel();
            TermuxResultReceiver.cancel(requestId, future);
        }
    }




    static String resultIntentDataUri(String requestId) {
        if (requestId == null || requestId.trim().isEmpty()) {
            throw new IllegalArgumentException("A non-empty request id is required.");
        }
        return "mahoraga://termux-result/" + requestId;
    }

    static boolean requiresCrossAppFgsReview(
            int platformApi, int callerTargetSdk, int serviceTargetSdk
    ) {
        return platformApi >= 31 && callerTargetSdk >= 31 && serviceTargetSdk >= 31;
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
