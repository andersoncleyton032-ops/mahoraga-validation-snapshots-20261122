package com.mahoraga.runtime;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

public final class TermuxResultReceiver extends BroadcastReceiver {
    public static final String ACTION_RESULT =
            "com.mahoraga.runtime.TERMUX_RESULT";
    public static final String EXTRA_REQUEST_ID = "request_id";
    public static final String EXTRA_RESULT_BUNDLE = "result";

    private static final ConcurrentHashMap<String, CompletableFuture<Bundle>> WAITERS =
            new ConcurrentHashMap<>();

    public static CompletableFuture<Bundle> register(String requestId) {
        CompletableFuture<Bundle> future = new CompletableFuture<>();
        CompletableFuture<Bundle> previous = WAITERS.putIfAbsent(requestId, future);
        if (previous != null) {
            throw new IllegalStateException("Duplicate Termux result request id.");
        }
        return future;
    }

    public static Bundle await(
            String requestId,
            CompletableFuture<Bundle> future,
            long timeoutSeconds
    ) throws Exception {
        try {
            return future.get(timeoutSeconds, TimeUnit.SECONDS);
        } catch (TimeoutException timeout) {
            return null;
        } finally {
            WAITERS.remove(requestId, future);
        }
    }

    public static void cancel(String requestId, CompletableFuture<Bundle> future) {
        WAITERS.remove(requestId, future);
        future.cancel(false);
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION_RESULT.equals(intent.getAction())) return;
        String requestId = intent.getStringExtra(EXTRA_REQUEST_ID);
        if (requestId == null) return;
        CompletableFuture<Bundle> future = WAITERS.get(requestId);
        if (future == null) return;
        Bundle result = intent.getBundleExtra(EXTRA_RESULT_BUNDLE);
        future.complete(result == null ? new Bundle() : new Bundle(result));
    }
}
