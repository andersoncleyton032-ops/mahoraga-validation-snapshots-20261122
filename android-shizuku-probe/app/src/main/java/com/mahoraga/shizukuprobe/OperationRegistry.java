package com.mahoraga.shizukuprobe;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.FutureTask;

/** Atomic admission, cancellation, completion and destroy coordination for remote operations. */
final class OperationRegistry {
    static final int ACCEPTED = 0;
    static final int REJECT_STOPPING = ProbeContract.REJECT_SERVICE_STOPPING;
    static final int REJECT_DUPLICATE = ProbeContract.REJECT_DUPLICATE_REQUEST_ID;

    static final class Entry {
        final ServiceLifecycle.Operation terminal;
        volatile FutureTask<Void> task;

        Entry(String requestId) {
            terminal = new ServiceLifecycle.Operation(0L, requestId);
        }
    }

    private final Map<String, Entry> pending = new HashMap<>();
    private boolean destroyed;

    synchronized int register(Entry entry) {
        if (destroyed) return REJECT_STOPPING;
        if (pending.containsKey(entry.terminal.requestId)) return REJECT_DUPLICATE;
        pending.put(entry.terminal.requestId, entry);
        return ACCEPTED;
    }

    synchronized boolean complete(Entry entry) {
        if (destroyed || !entry.terminal.complete()) return false;
        pending.remove(entry.terminal.requestId, entry);
        return true;
    }

    synchronized boolean fail(Entry entry) {
        if (destroyed || !entry.terminal.fail()) return false;
        pending.remove(entry.terminal.requestId, entry);
        return true;
    }

    boolean cancel(String requestId) {
        Entry entry;
        synchronized (this) {
            entry = pending.get(requestId);
            if (entry == null || !entry.terminal.cancel()) return false;
            pending.remove(requestId, entry);
        }
        FutureTask<Void> task = entry.task;
        if (task != null) task.cancel(true);
        return true;
    }

    List<Entry> destroyAndCancelPending() {
        List<Entry> cancelled = new ArrayList<>();
        synchronized (this) {
            if (destroyed) return cancelled;
            destroyed = true;
            for (Map.Entry<String, Entry> item : pending.entrySet()) {
                Entry entry = item.getValue();
                if (entry.terminal.cancel()) {
                    cancelled.add(entry);
                }
            }
            pending.clear();
        }
        for (Entry entry : cancelled) {
            FutureTask<Void> task = entry.task;
            if (task != null) task.cancel(true);
        }
        return cancelled;
    }

    synchronized boolean isDestroyed() {
        return destroyed;
    }

    synchronized int pendingCount() {
        return pending.size();
    }
}
