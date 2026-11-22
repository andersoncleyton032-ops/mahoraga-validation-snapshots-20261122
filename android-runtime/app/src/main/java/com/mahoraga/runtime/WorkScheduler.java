package com.mahoraga.runtime;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import java.util.concurrent.TimeUnit;

public final class WorkScheduler {
    public static final String ONE_SHOT_WORK = "mahoraga.background.serial";
    public static final String PERIODIC_POLL_WORK = "mahoraga.background.poll";
    private static final String PREFS = "mahoraga_background_work";
    private static final String KEY_ENABLED = "enabled";

    private WorkScheduler() {}

    public static boolean isEnabled(Context context) {
        return preferences(context).getBoolean(KEY_ENABLED, false);
    }

    public static void start(Context context) {
        Context app = context.getApplicationContext();
        preferences(app).edit().putBoolean(KEY_ENABLED, true).apply();
        enqueuePeriodicPoll(app);
        enqueueInitial(app);
    }

    public static void stop(Context context) {
        Context app = context.getApplicationContext();
        preferences(app).edit().putBoolean(KEY_ENABLED, false).apply();
        WorkManager manager = WorkManager.getInstance(app);
        manager.cancelUniqueWork(ONE_SHOT_WORK);
        manager.cancelUniqueWork(PERIODIC_POLL_WORK);
    }

    public static void enqueueInitial(Context context) {
        Context app = context.getApplicationContext();
        if (!isEnabled(app)) return;
        OneTimeWorkRequest request = buildOneShot(0);
        WorkManager.getInstance(app).enqueueUniqueWork(
                ONE_SHOT_WORK,
                ExistingWorkPolicy.KEEP,
                request
        );
    }

    public static void enqueueNext(Context context, int delaySeconds) {
        Context app = context.getApplicationContext();
        if (!isEnabled(app) || !WorkPolicy.isValidNextDelay(delaySeconds)) return;
        OneTimeWorkRequest request = buildOneShot(delaySeconds);
        WorkManager.getInstance(app)
                .beginUniqueWork(
                        ONE_SHOT_WORK,
                        ExistingWorkPolicy.APPEND_OR_REPLACE,
                        request
                )
                .enqueue();
    }

    private static void enqueuePeriodicPoll(Context context) {
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(
                MahoragaOneShotWorker.class,
                WorkPolicy.POLL_INTERVAL_MINUTES,
                TimeUnit.MINUTES
        )
                .setInitialDelay(WorkPolicy.POLL_INTERVAL_MINUTES, TimeUnit.MINUTES)
                .setConstraints(buildConstraints())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC_POLL_WORK,
                ExistingPeriodicWorkPolicy.KEEP,
                request
        );
    }

    private static OneTimeWorkRequest buildOneShot(int delaySeconds) {
        return new OneTimeWorkRequest.Builder(MahoragaOneShotWorker.class)
                .setInitialDelay(delaySeconds, TimeUnit.SECONDS)
                .setConstraints(buildConstraints())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS)
                .build();
    }

    private static Constraints buildConstraints() {
        // Resource admission is dynamic in AutonomyGovernor. WorkManager only
        // requires no network; low battery/storage are not hard scheduling gates.
        return new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.NOT_REQUIRED)
                .build();
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
