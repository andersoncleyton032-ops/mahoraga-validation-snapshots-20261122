package com.mahoraga.shizukuprobe;

import static org.junit.Assert.*;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.Test;

public final class ServiceLifecycleTest {
    @Test
    public void staleGenerationCannotAdvanceOrAffectReplacementSession() {
        ServiceLifecycle lifecycle = new ServiceLifecycle();
        ServiceLifecycle.Session old = lifecycle.begin();
        assertNotNull(old);
        assertTrue(lifecycle.markConnected(old));
        assertTrue(lifecycle.markVerifying(old));
        assertTrue(lifecycle.invalidate(old));

        ServiceLifecycle.Session current = lifecycle.begin();
        assertNotNull(current);
        assertTrue(current.generation > old.generation);
        assertFalse(lifecycle.isCurrent(old));
        assertFalse(lifecycle.markReady(old));
        assertTrue(lifecycle.isCurrent(current));
        assertTrue(lifecycle.markConnected(current));
        assertTrue(lifecycle.markVerifying(current));
        assertTrue(lifecycle.markReady(current));
    }

    @Test
    public void onlyOneSessionCanOwnTheLifecycle() {
        ServiceLifecycle lifecycle = new ServiceLifecycle();
        ServiceLifecycle.Session first = lifecycle.begin();
        assertNotNull(first);
        assertNull(lifecycle.begin());
        assertTrue(lifecycle.invalidate(first));
        assertNotNull(lifecycle.begin());
    }

    @Test
    public void protocolCannotBecomeReadyBeforeConnectionAndHandshake() {
        ServiceLifecycle lifecycle = new ServiceLifecycle();
        ServiceLifecycle.Session session = lifecycle.begin();
        assertFalse(lifecycle.markReady(session));
        assertFalse(lifecycle.markVerifying(session));
        assertTrue(lifecycle.markConnected(session));
        assertFalse(lifecycle.markReady(session));
        assertTrue(lifecycle.markVerifying(session));
        assertTrue(lifecycle.markReady(session));
    }

    @Test
    public void cancellationSuppressesEveryLateCompletion() {
        ServiceLifecycle.Operation operation =
                new ServiceLifecycle.Operation(7L, "550e8400-e29b-41d4-a716-446655440000");
        assertTrue(operation.cancel());
        assertFalse(operation.complete());
        assertFalse(operation.fail());
        assertEquals(ServiceLifecycle.Operation.Terminal.CANCELLED, operation.terminal());
    }

    @Test
    public void completionAndCancellationHaveExactlyOneAtomicWinner() throws Exception {
        for (int iteration = 0; iteration < 250; iteration++) {
            ServiceLifecycle.Operation operation =
                    new ServiceLifecycle.Operation(iteration, "request-" + iteration);
            CountDownLatch ready = new CountDownLatch(2);
            CountDownLatch start = new CountDownLatch(1);
            AtomicInteger winners = new AtomicInteger();
            AtomicReference<ServiceLifecycle.Operation.Terminal> winner =
                    new AtomicReference<>();

            Thread completion = new Thread(() -> {
                ready.countDown();
                await(start);
                if (operation.complete()) {
                    winners.incrementAndGet();
                    winner.set(ServiceLifecycle.Operation.Terminal.COMPLETED);
                }
            });
            Thread cancellation = new Thread(() -> {
                ready.countDown();
                await(start);
                if (operation.cancel()) {
                    winners.incrementAndGet();
                    winner.set(ServiceLifecycle.Operation.Terminal.CANCELLED);
                }
            });
            completion.start();
            cancellation.start();
            assertTrue(ready.await(2, TimeUnit.SECONDS));
            start.countDown();
            completion.join(2_000);
            cancellation.join(2_000);
            assertFalse(completion.isAlive());
            assertFalse(cancellation.isAlive());
            assertEquals(1, winners.get());
            assertEquals(winner.get(), operation.terminal());
        }
    }

    @Test
    public void handshakeResultAndTimeoutHaveExactlyOneWinner() throws Exception {
        for (int iteration = 0; iteration < 100; iteration++) {
            OneShotGate gate = new OneShotGate();
            CountDownLatch ready = new CountDownLatch(2);
            CountDownLatch start = new CountDownLatch(1);
            AtomicInteger winners = new AtomicInteger();
            Thread result = new Thread(() -> {
                ready.countDown();
                await(start);
                if (gate.tryFinish()) winners.incrementAndGet();
            });
            Thread timeout = new Thread(() -> {
                ready.countDown();
                await(start);
                if (gate.tryFinish()) winners.incrementAndGet();
            });
            result.start();
            timeout.start();
            assertTrue(ready.await(2, TimeUnit.SECONDS));
            start.countDown();
            result.join(2_000);
            timeout.join(2_000);
            assertFalse(result.isAlive());
            assertFalse(timeout.isAlive());
            assertEquals(1, winners.get());
            assertTrue(gate.isFinished());
        }
    }

    @Test
    public void binderDeathInvalidatesSessionAndMakesPendingCallbackStale() {
        ServiceLifecycle lifecycle = new ServiceLifecycle();
        ServiceLifecycle.Session session = lifecycle.begin();
        ServiceLifecycle.Operation operation =
                new ServiceLifecycle.Operation(session.generation, "request-binder-death");
        assertTrue(lifecycle.invalidate(session));
        assertTrue(operation.cancel());
        assertFalse(lifecycle.isCurrent(session));
        assertFalse(operation.complete());
    }

    @Test
    public void serializedQueuePreservesBindCancelUnbindOrderWithoutOverlap() throws Exception {
        SerialCommandQueue queue = new SerialCommandQueue("lifecycle-test");
        CountDownLatch firstEntered = new CountDownLatch(1);
        CountDownLatch releaseFirst = new CountDownLatch(1);
        CountDownLatch finished = new CountDownLatch(4);
        List<String> order = Collections.synchronizedList(new ArrayList<>());
        AtomicInteger active = new AtomicInteger();
        AtomicInteger maxActive = new AtomicInteger();

        queue.execute(() -> {
            int now = active.incrementAndGet();
            maxActive.accumulateAndGet(now, Math::max);
            firstEntered.countDown();
            await(releaseFirst);
            order.add("bind");
            active.decrementAndGet();
            finished.countDown();
        });
        assertTrue(firstEntered.await(2, TimeUnit.SECONDS));

        queue.execute(command("cancel", order, active, maxActive, finished));
        queue.execute(command("unbind", order, active, maxActive, finished));
        queue.execute(command("next-bind", order, active, maxActive, finished));
        assertTrue(order.isEmpty());

        releaseFirst.countDown();
        assertTrue(finished.await(2, TimeUnit.SECONDS));
        queue.shutdown();
        assertEquals(java.util.Arrays.asList("bind", "cancel", "unbind", "next-bind"), order);
        assertEquals(1, maxActive.get());
    }

    private static Runnable command(
            String name, List<String> order, AtomicInteger active,
            AtomicInteger maxActive, CountDownLatch finished
    ) {
        return () -> {
            int now = active.incrementAndGet();
            maxActive.accumulateAndGet(now, Math::max);
            order.add(name);
            active.decrementAndGet();
            finished.countDown();
        };
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
    @Test
    public void activityRecreationGetsDistinctUserServiceIdentity() {
        ServiceLifecycle processLifecycle = new ServiceLifecycle();
        ServiceLifecycle.Session oldActivitySession = processLifecycle.begin();
        assertNotNull(oldActivitySession);
        String oldTag = ProbeContract.userServiceTag(oldActivitySession.generation);
        String oldProcessSuffix = ProbeContract.userServiceProcessSuffix(
                oldActivitySession.generation
        );
        assertTrue(processLifecycle.invalidate(oldActivitySession));

        ServiceLifecycle.Session recreatedActivitySession = processLifecycle.begin();
        assertNotNull(recreatedActivitySession);
        assertTrue(recreatedActivitySession.generation > oldActivitySession.generation);
        assertNotEquals(oldTag, ProbeContract.userServiceTag(recreatedActivitySession.generation));
        assertNotEquals(
                oldProcessSuffix,
                ProbeContract.userServiceProcessSuffix(recreatedActivitySession.generation)
        );
    }

}
