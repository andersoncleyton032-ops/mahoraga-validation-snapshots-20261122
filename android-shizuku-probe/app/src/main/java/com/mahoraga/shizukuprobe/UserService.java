package com.mahoraga.shizukuprobe;

import android.os.Process;
import android.os.RemoteException;
import android.os.SystemClock;
import android.util.Log;

import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.FutureTask;
import java.util.concurrent.RejectedExecutionException;

public final class UserService extends IUserService.Stub {
    private static final String TAG = "MahoragaUserService";

    private final OperationRegistry operations = new OperationRegistry();
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

        OperationRegistry.Entry record = new OperationRegistry.Entry(requestId);
        FutureTask<Void> task = new FutureTask<>(() -> {
            try {
                if (Thread.currentThread().isInterrupted() || operations.isDestroyed()) return null;
                int uid = Process.myUid();
                int pid = Process.myPid();
                long completedAt = SystemClock.elapsedRealtime();
                if (!operations.complete(record)) return null;
                if (uid != 2000) {
                    callback.onRejected(requestId, ProbeContract.REJECT_UID_NOT_SHELL);
                } else {
                    callback.onCompleted(requestId, uid, pid, completedAt);
                }
            } catch (RemoteException callbackFailure) {
                Log.w(TAG, "client callback is no longer available");
            } catch (RuntimeException operationFailure) {
                Log.e(TAG, "identity probe failed", operationFailure);
            } finally {
                operations.fail(record);
            }
            return null;
        });
        record.task = task;

        int admissionRejection = operations.register(record);
        if (admissionRejection != 0) {
            reject(callback, requestId, admissionRejection);
            return;
        }

        try {
            worker.execute(task);
        } catch (RejectedExecutionException stopping) {
            if (operations.cancel(requestId)) {
                reject(callback, requestId, ProbeContract.REJECT_SERVICE_STOPPING);
            }
        }
    }

    @Override
    public void cancelIdentityProbe(String requestId) {
        if (!ProbeContract.isValidRequestId(requestId)) return;
        operations.cancel(requestId);
    }

    @Override
    public void destroy() {
        int cancelledCount = operations.destroyAndCancelPending().size();
        worker.shutdownNow();
        Log.i(TAG, "destroy requested; cancelled=" + cancelledCount);
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
