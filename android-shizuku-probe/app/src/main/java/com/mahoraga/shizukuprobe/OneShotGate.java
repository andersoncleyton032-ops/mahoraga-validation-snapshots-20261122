package com.mahoraga.shizukuprobe;

import java.util.concurrent.atomic.AtomicBoolean;

/** Exactly one of a handshake result or its timeout may claim completion. */
final class OneShotGate {
    private final AtomicBoolean finished = new AtomicBoolean(false);

    boolean tryFinish() {
        return finished.compareAndSet(false, true);
    }

    boolean isFinished() {
        return finished.get();
    }
}
