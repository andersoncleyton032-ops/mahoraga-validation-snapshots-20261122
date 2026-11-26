package com.mahoraga.shizukuprobe;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Main-process lifecycle gate. A callback is valid only for the exact live session. */
final class ServiceLifecycle {
    enum State { BINDING, CONNECTED, VERIFYING_PROTOCOL, READY, STOPPED }

    static final class Session {
        final long generation;
        private volatile State state = State.BINDING;
        private final AtomicBoolean closed = new AtomicBoolean(false);

        private Session(long generation) {
            this.generation = generation;
        }

        State state() { return state; }
        boolean isClosed() { return closed.get(); }
    }

    static final class Operation {
        enum Terminal { PENDING, COMPLETED, CANCELLED, FAILED }

        final long generation;
        final String requestId;
        private final AtomicReference<Terminal> terminal =
                new AtomicReference<>(Terminal.PENDING);

        Operation(long generation, String requestId) {
            this.generation = generation;
            this.requestId = requestId;
        }

        boolean complete() {
            return terminal.compareAndSet(Terminal.PENDING, Terminal.COMPLETED);
        }

        boolean cancel() {
            return terminal.compareAndSet(Terminal.PENDING, Terminal.CANCELLED);
        }

        boolean fail() {
            return terminal.compareAndSet(Terminal.PENDING, Terminal.FAILED);
        }

        boolean isPending() {
            return terminal.get() == Terminal.PENDING;
        }

        Terminal terminal() {
            return terminal.get();
        }
    }

    private long nextGeneration;
    private Session active;

    synchronized Session begin() {
        if (active != null) return null;
        active = new Session(++nextGeneration);
        return active;
    }

    synchronized boolean isCurrent(Session session) {
        return session != null && active == session && !session.isClosed();
    }

    synchronized boolean markConnected(Session session) {
        if (!isCurrent(session) || session.state != State.BINDING) return false;
        session.state = State.CONNECTED;
        return true;
    }

    synchronized boolean markVerifying(Session session) {
        if (!isCurrent(session) || session.state != State.CONNECTED) return false;
        session.state = State.VERIFYING_PROTOCOL;
        return true;
    }

    synchronized boolean markReady(Session session) {
        if (!isCurrent(session) || session.state != State.VERIFYING_PROTOCOL) return false;
        session.state = State.READY;
        return true;
    }

    synchronized boolean invalidate(Session session) {
        if (session == null || active != session) return false;
        active = null;
        session.closed.set(true);
        session.state = State.STOPPED;
        ++nextGeneration;
        return true;
    }

    synchronized Session active() {
        return active;
    }
}
