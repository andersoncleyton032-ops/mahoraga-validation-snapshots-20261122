package com.mahoraga.runtime;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.SystemClock;

public final class WakeRequestReceiver extends BroadcastReceiver {
    private static final String ACTION =
            "com.mahoraga.runtime.ENQUEUE_BACKGROUND_WORK";
    private static final String PREFS = "mahoraga_background_work";
    private static final String KEY_LAST_EXTERNAL_WAKE = "last_external_wake_elapsed";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION.equals(intent.getAction())) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            try {
                int termuxUid = context.getPackageManager()
                        .getApplicationInfo(TermuxBridge.TERMUX_PACKAGE, 0).uid;
                if (!WorkPolicy.isTrustedWakeSender(
                        Build.VERSION.SDK_INT, getSentFromUid(), termuxUid
                )) return;
            } catch (PackageManager.NameNotFoundException missingTermux) {
                return;
            }
        }
        if (!WorkScheduler.isEnabled(context)) return;

        int delay = intent.getIntExtra("delay_seconds", -1);
        if (!WorkPolicy.isValidNextDelay(delay)) return;

        SharedPreferences preferences =
                context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long now = SystemClock.elapsedRealtime();
        long last = preferences.getLong(KEY_LAST_EXTERNAL_WAKE, 0L);
        if (last > 0L && now >= last
                && now - last < WorkPolicy.RECEIVER_RATE_LIMIT_MS) {
            return;
        }
        preferences.edit().putLong(KEY_LAST_EXTERNAL_WAKE, now).apply();
        WorkScheduler.enqueueNext(context, delay);
    }
}
