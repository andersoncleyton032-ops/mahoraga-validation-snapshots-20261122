package com.mahoraga.shizukuprobe;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;

/** FIFO command queue shared by bind, operation, cancel and unbind IPC. */
final class SerialCommandQueue {
    private final ExecutorService executor;

    SerialCommandQueue(String threadName) {
        ThreadFactory factory = runnable -> {
            Thread thread = new Thread(runnable, threadName);
            thread.setDaemon(true);
            return thread;
        };
        executor = Executors.newSingleThreadExecutor(factory);
    }

    void execute(Runnable command) {
        executor.execute(command);
    }

    void shutdown() {
        executor.shutdown();
    }
}
