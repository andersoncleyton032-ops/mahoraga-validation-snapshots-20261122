package com.mahoraga.runtime;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.SystemClock;

public final class WakeRequestReceiver extends BroadcastReceiver {
    private static final String ACTION =
            "com.mahoraga.runtime.ENQUEUE_BACKGROUND_WORK";
    private static final String PREFS = "mahoraga_background_work";
    private static final String KEY_LAST_EXTERNAL_WAKE = "last_external_wake_elapsed";

    static final int RESULT_ACCEPTED = 1;
    static final int RESULT_INVALID_REQUEST = 2;
    static final int RESULT_UNTRUSTED_SENDER = 3;
    static final int RESULT_DISABLED = 4;
    static final int RESULT_INVALID_DELAY = 5;
    static final int RESULT_RATE_LIMITED = 6;
    static final int RESULT_ENQUEUE_FAILED = 7;

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION.equals(intent.getAction())) {
            finishOrdered(RESULT_INVALID_REQUEST);
            return;
        }
        int senderUid = Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE
                ? getSentFromUid()
                : -1;
        try {
            int termuxUid = context.getPackageManager()
                    .getApplicationInfo(TermuxBridge.TERMUX_PACKAGE, 0).uid;
            if (!WorkPolicy.isTrustedWakeSender(
                    Build.VERSION.SDK_INT, senderUid, termuxUid
            )) {
                finishOrdered(RESULT_UNTRUSTED_SENDER);
                return;
            }
        } catch (PackageManager.NameNotFoundException missingTermux) {
            finishOrdered(RESULT_UNTRUSTED_SENDER);
            return;
        } catch (RuntimeException senderInspectionFailure) {
            finishOrdered(RESULT_UNTRUSTED_SENDER);
            return;
        }
        if (!WorkScheduler.isEnabled(context)) {
            finishOrdered(RESULT_DISABLED);
            return;
        }

        int delay = intent.getIntExtra("delay_seconds", -1);
        if (!WorkPolicy.isValidNextDelay(delay)) {
            finishOrdered(RESULT_INVALID_DELAY);
            return;
        }

        SharedPreferences preferences =
                context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long now = SystemClock.elapsedRealtime();
        long last = preferences.getLong(KEY_LAST_EXTERNAL_WAKE, 0L);
        if (last > 0L && now >= last
                && now - last < WorkPolicy.RECEIVER_RATE_LIMIT_MS) {
            finishOrdered(RESULT_RATE_LIMITED);
            return;
        }

        try {
            if (!WorkScheduler.enqueueNext(context, delay)) {
                finishOrdered(RESULT_ENQUEUE_FAILED);
                return;
            }
            preferences.edit().putLong(KEY_LAST_EXTERNAL_WAKE, now).apply();
            finishOrdered(RESULT_ACCEPTED);
        } catch (RuntimeException enqueueFailure) {
            finishOrdered(RESULT_ENQUEUE_FAILED);
        }
    }

    private void finishOrdered(int resultCode) {
        if (isOrderedBroadcast()) {
            setResultCode(resultCode);
        }
    }
}
