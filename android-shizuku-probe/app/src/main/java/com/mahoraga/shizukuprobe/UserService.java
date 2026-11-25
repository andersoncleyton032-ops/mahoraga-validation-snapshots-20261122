package com.mahoraga.shizukuprobe;

import android.os.Process;
import android.os.RemoteException;
import android.os.SystemClock;
import android.util.Log;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;

public final class UserService extends IUserService.Stub {
    private static final String TAG = "MahoragaUserService";
    private final AtomicBoolean destroyed = new AtomicBoolean(false);
    private final ConcurrentHashMap<String, Future<?>> pending = new ConcurrentHashMap<>();
    private final ExecutorService worker = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "mahoraga-shizuku-probe");
        thread.setDaemon(true);
        return thread;
    });

    public UserService() {
        Log.i(TAG, "created");
    }

    @Override
    public int getProtocolVersion() {
        return ProbeContract.PROTOCOL_VERSION;
    }

    @Override
    public void runIdentityProbe(String requestId, IProbeCallback callback) {
        if (callback == null) return;
        if (!ProbeContract.isValidRequestId(requestId)) {
            reject(callback, requestId, ProbeContract.REJECT_INVALID_REQUEST_ID);
            return;
        }
        if (destroyed.get()) {
            reject(callback, requestId, ProbeContract.REJECT_SERVICE_STOPPING);
            return;
        }

        FutureTask<Void> task = new FutureTask<>(() -> {
            try {
                if (Thread.currentThread().isInterrupted() || destroyed.get()) return null;
                int uid = Process.myUid();
                int pid = Process.myPid();
                long completedAt = SystemClock.elapsedRealtime();
                if (uid != 2000) {
                    callback.onRejected(requestId, ProbeContract.REJECT_UID_NOT_SHELL);
                } else {
                    callback.onCompleted(requestId, uid, pid, completedAt);
                }
            } catch (RemoteException callbackFailure) {
                Log.w(TAG, "client callback is no longer available");
            } finally {
                pending.remove(requestId);
            }
            return null;
        });

        if (pending.putIfAbsent(requestId, task) != null) {
            reject(callback, requestId, ProbeContract.REJECT_DUPLICATE_REQUEST_ID);
            return;
        }
        try {
            worker.execute(task);
        } catch (RejectedExecutionException stopping) {
            pending.remove(requestId, task);
            reject(callback, requestId, ProbeContract.REJECT_SERVICE_STOPPING);
        }
    }

    @Override
    public void cancelIdentityProbe(String requestId) {
        if (!ProbeContract.isValidRequestId(requestId)) return;
        Future<?> task = pending.remove(requestId);
        if (task != null) task.cancel(true);
    }

    @Override
    public void destroy() {
        if (!destroyed.compareAndSet(false, true)) return;
        for (Future<?> task : pending.values()) task.cancel(true);
        pending.clear();
        worker.shutdownNow();
        Log.i(TAG, "destroy requested; terminating UserService process");
        System.exit(0);
    }

    private static void reject(IProbeCallback callback, String requestId, int reasonCode) {
        try {
            callback.onRejected(requestId == null ? "" : requestId, reasonCode);
        } catch (RemoteException ignored) {
            // The client disappeared; no persistent state is retained.
        }
    }
}