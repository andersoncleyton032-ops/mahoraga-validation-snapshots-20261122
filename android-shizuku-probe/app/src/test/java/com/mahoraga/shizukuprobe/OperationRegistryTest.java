package com.mahoraga.shizukuprobe;

import static org.junit.Assert.*;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import org.junit.Test;

public final class OperationRegistryTest {
    @Test
    public void rejectsDuplicateIdsWithoutReplacingOriginalOperation() {
        OperationRegistry registry = new OperationRegistry();
        OperationRegistry.Entry first = new OperationRegistry.Entry("same-id");
        OperationRegistry.Entry duplicate = new OperationRegistry.Entry("same-id");
        assertEquals(OperationRegistry.ACCEPTED, registry.register(first));
        assertEquals(OperationRegistry.REJECT_DUPLICATE, registry.register(duplicate));
        assertEquals(1, registry.pendingCount());
        assertTrue(registry.cancel("same-id"));
        assertEquals(ServiceLifecycle.Operation.Terminal.CANCELLED, first.terminal.terminal());
        assertEquals(ServiceLifecycle.Operation.Terminal.PENDING, duplicate.terminal.terminal());
    }

    @Test
    public void destroyAtomicallyCancelsPendingAndRejectsFutureAdmission() {
        OperationRegistry registry = new OperationRegistry();
        OperationRegistry.Entry pending = new OperationRegistry.Entry("pending-before-destroy");
        assertEquals(OperationRegistry.ACCEPTED, registry.register(pending));

        List<OperationRegistry.Entry> cancelled = registry.destroyAndCancelPending();
        assertEquals(1, cancelled.size());
        assertEquals(ServiceLifecycle.Operation.Terminal.CANCELLED, pending.terminal.terminal());
        assertEquals(0, registry.pendingCount());
        assertTrue(registry.isDestroyed());
        assertEquals(OperationRegistry.REJECT_STOPPING,
                registry.register(new OperationRegistry.Entry("after-destroy")));
        assertFalse(registry.complete(pending));
    }

    @Test
    public void failedOperationIsRemovedAndCannotLaterComplete() {
        OperationRegistry registry = new OperationRegistry();
        OperationRegistry.Entry failed = new OperationRegistry.Entry("failed-operation");
        assertEquals(OperationRegistry.ACCEPTED, registry.register(failed));
        assertTrue(registry.fail(failed));
        assertEquals(0, registry.pendingCount());
        assertEquals(ServiceLifecycle.Operation.Terminal.FAILED, failed.terminal.terminal());
        assertFalse(registry.complete(failed));
    }

    @Test
    public void completionThatWinsBeforeDestroyRemainsTheTerminalOutcome() {
        OperationRegistry registry = new OperationRegistry();
        OperationRegistry.Entry completed = new OperationRegistry.Entry("completed-first");
        assertEquals(OperationRegistry.ACCEPTED, registry.register(completed));
        assertTrue(registry.complete(completed));
        assertTrue(registry.destroyAndCancelPending().isEmpty());
        assertEquals(ServiceLifecycle.Operation.Terminal.COMPLETED,
                completed.terminal.terminal());
    }

    @Test
    public void destroyAndCompletionRaceHasExactlyOneTerminalWinner() throws Exception {
        for (int iteration = 0; iteration < 200; iteration++) {
            OperationRegistry registry = new OperationRegistry();
            OperationRegistry.Entry entry = new OperationRegistry.Entry("race-" + iteration);
            assertEquals(OperationRegistry.ACCEPTED, registry.register(entry));
            CountDownLatch ready = new CountDownLatch(2);
            CountDownLatch start = new CountDownLatch(1);
            AtomicBoolean completed = new AtomicBoolean();
            AtomicBoolean destroyed = new AtomicBoolean();

            Thread completion = new Thread(() -> {
                ready.countDown();
                await(start);
                completed.set(registry.complete(entry));
            });
            Thread destroy = new Thread(() -> {
                ready.countDown();
                await(start);
                destroyed.set(!registry.destroyAndCancelPending().isEmpty());
            });
            completion.start();
            destroy.start();
            assertTrue(ready.await(2, TimeUnit.SECONDS));
            start.countDown();
            completion.join(2_000);
            destroy.join(2_000);
            assertFalse(completion.isAlive());
            assertFalse(destroy.isAlive());
            assertTrue(completed.get() ^ destroyed.get());
            assertEquals(completed.get()
                            ? ServiceLifecycle.Operation.Terminal.COMPLETED
                            : ServiceLifecycle.Operation.Terminal.CANCELLED,
                    entry.terminal.terminal());
            assertEquals(0, registry.pendingCount());
        }
    }

    @Test
    public void cancellationAndDestroyCannotBothOwnTheSamePendingOperation() throws Exception {
        OperationRegistry registry = new OperationRegistry();
        OperationRegistry.Entry entry = new OperationRegistry.Entry("cancel-destroy-race");
        assertEquals(OperationRegistry.ACCEPTED, registry.register(entry));
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        AtomicBoolean cancelled = new AtomicBoolean();
        AtomicBoolean destroyedEntry = new AtomicBoolean();

        Thread cancel = new Thread(() -> {
            ready.countDown();
            await(start);
            cancelled.set(registry.cancel(entry.terminal.requestId));
        });
        Thread destroy = new Thread(() -> {
            ready.countDown();
            await(start);
            destroyedEntry.set(!registry.destroyAndCancelPending().isEmpty());
        });
        cancel.start();
        destroy.start();
        assertTrue(ready.await(2, TimeUnit.SECONDS));
        start.countDown();
        cancel.join(2_000);
        destroy.join(2_000);
        assertFalse(cancel.isAlive());
        assertFalse(destroy.isAlive());
        assertTrue(cancelled.get() ^ destroyedEntry.get());
        assertEquals(ServiceLifecycle.Operation.Terminal.CANCELLED, entry.terminal.terminal());
        assertEquals(0, registry.pendingCount());
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(2, TimeUnit.SECONDS)) {
                throw new AssertionError("Timed out waiting for deterministic test latch");
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new AssertionError(interrupted);
        }
    }
}
