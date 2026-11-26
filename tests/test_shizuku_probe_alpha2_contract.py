from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA_ROOT = ROOT / "android-shizuku-probe" / "app" / "src" / "main" / "java" / "com" / "mahoraga" / "shizukuprobe"
AIDL_ROOT = ROOT / "android-shizuku-probe" / "app" / "src" / "main" / "aidl" / "com" / "mahoraga" / "shizukuprobe"


def test_aidl_exposes_only_typed_identity_operation_and_lifecycle():
    service = (AIDL_ROOT / "IUserService.aidl").read_text(encoding="utf-8")
    callback = (AIDL_ROOT / "IProbeCallback.aidl").read_text(encoding="utf-8")

    assert "getProtocolVersion()" in service
    assert "import com.mahoraga.shizukuprobe.IProbeCallback;" in service
    assert "runIdentityProbe(String requestId, IProbeCallback callback)" in service
    assert "cancelIdentityProbe(String requestId)" in service
    assert "getProtocolVersion() = 1" in service
    assert "runIdentityProbe(String requestId, IProbeCallback callback) = 2" in service
    assert "cancelIdentityProbe(String requestId) = 3" in service
    assert "destroy() = 16777114" in service
    assert "String command" not in service
    assert "String[] args" not in service
    assert "onCompleted(String requestId, int uid, int pid, long elapsedRealtimeMillis)" in callback
    assert "onRejected(String requestId, int reasonCode)" in callback


def test_user_service_uses_operation_registry_and_bounded_worker_lifecycle():
    service = (JAVA_ROOT / "UserService.java").read_text(encoding="utf-8")
    assert "Process.myUid()" in service
    assert "uid != 2000" in service
    assert "Executors.newSingleThreadExecutor" in service
    assert "operations.register(record)" in service
    assert "operations.complete(record)" in service
    assert "operations.fail(record)" in service
    assert "operations.cancel(requestId)" in service
    assert "operations.destroyAndCancelPending()" in service
    assert "worker.shutdownNow()" in service
    assert "System.exit(0)" in service


def test_operation_registry_coordinates_admission_completion_cancel_and_destroy():
    registry = (JAVA_ROOT / "OperationRegistry.java").read_text(encoding="utf-8")
    assert "synchronized int register(Entry entry)" in registry
    assert "synchronized boolean complete(Entry entry)" in registry
    assert "synchronized boolean fail(Entry entry)" in registry
    assert "destroyed || !entry.terminal.complete()" in registry
    assert "entry.terminal.cancel()" in registry
    assert "pending.clear()" in registry
    assert "REJECT_DUPLICATE" in registry
    assert "REJECT_STOPPING" in registry


def test_activity_uses_generation_scoped_connections_and_ignores_stale_callbacks():
    activity = (JAVA_ROOT / "MainActivity.java").read_text(encoding="utf-8")
    assert "new ConnectionContext(token)" in activity
    assert "new ServiceConnection()" in activity
    assert "lifecycle.isCurrent(context.token)" in activity
    assert "enqueueStaleConnectionRemoval(context)" in activity
    assert "private static final ServiceLifecycle lifecycle" in activity
    assert "final Shizuku.UserServiceArgs userServiceArgs" in activity
    assert "createUserServiceArgs(token.generation)" in activity
    assert "ProbeContract.userServiceTag(generation)" in activity
    assert "ProbeContract.userServiceProcessSuffix(generation)" in activity
    assert "Shizuku.unbindUserService(context.userServiceArgs, context.connection, true)" in activity
    assert "Shizuku.unbindUserService(userServiceArgs, context.connection, true)" not in activity
    assert "removeUserServiceGeneration(context)" in activity
    cleanup = activity.split("private void removeUserServiceGeneration", 1)[1].split(
        "private void stopUserService", 1
    )[0]
    detach = cleanup.index("Shizuku.unbindUserService(context.userServiceArgs, context.connection, false)")
    remove = cleanup.index("Shizuku.unbindUserService(context.userServiceArgs, context.connection, true)")
    assert detach < remove
    assert "linkToDeath(context.deathRecipient, 0)" in activity
    assert "operation.generation == context.token.generation" in activity


def test_activity_serializes_bind_run_cancel_and_unbind_across_recreation():
    activity = (JAVA_ROOT / "MainActivity.java").read_text(encoding="utf-8")
    queue = (JAVA_ROOT / "SerialCommandQueue.java").read_text(encoding="utf-8")
    assert "private static final SerialCommandQueue lifecycleExecutor" in activity
    assert "lifecycleExecutor.execute" in activity
    assert "private static final ExecutorService handshakeExecutor" in activity
    assert "new ThreadPoolExecutor(" in activity
    assert "0, 2, 30L, TimeUnit.SECONDS" in activity
    assert "final class SerialCommandQueue" in queue
    assert "Executors.newSingleThreadExecutor" in queue
    assert "lifecycleExecutor.shutdown()" not in activity


def test_activity_has_independent_bind_handshake_and_operation_timeouts():
    activity = (JAVA_ROOT / "MainActivity.java").read_text(encoding="utf-8")
    contract = (JAVA_ROOT / "ProbeContract.java").read_text(encoding="utf-8")
    assert "ProbeContract.BIND_TIMEOUT_MS" in activity
    assert "ProbeContract.HANDSHAKE_TIMEOUT_MS" in activity
    assert "ProbeContract.OPERATION_TIMEOUT_MS" in activity
    assert "HANDSHAKE_TIMEOUT_MS = 5_000" in contract
    assert "OneShotGate handshakeFinished" in activity
    assert "handshakeFinished.tryFinish()" in activity
    assert "if (!context.handshakeFinished.tryFinish()) return;" in activity
    assert "handshakeFinished.compareAndSet" not in activity


def test_activity_requires_explicit_actions_and_binder_death_cleanup():
    activity = (JAVA_ROOT / "MainActivity.java").read_text(encoding="utf-8")
    assert 'setText("Iniciar UserService de teste")' in activity
    assert 'setText("Executar prova de identidade")' in activity
    assert 'setText("Cancelar operação")' in activity
    assert 'setText("Encerrar UserService")' in activity
    assert ".daemon(false)" in activity
    assert ".tag(" in activity
    assert ".version(ProbeContract.USER_SERVICE_VERSION)" in activity
    assert "context.deathRecipient" in activity
    assert "USER_SERVICE_BINDER_DIED" in activity
    assert "SHIZUKU_BINDER_DIED" in activity
    assert "operation.cancel()" in activity


def test_probe_contains_no_arbitrary_process_or_network_execution():
    sources = [
        (JAVA_ROOT / "MainActivity.java").read_text(encoding="utf-8"),
        (JAVA_ROOT / "UserService.java").read_text(encoding="utf-8"),
        (AIDL_ROOT / "IUserService.aidl").read_text(encoding="utf-8"),
    ]
    combined = "\n".join(sources)
    forbidden = (
        "Runtime.getRuntime().exec",
        "new ProcessBuilder",
        "Shizuku.newProcess",
        "transactRemote(",
        "android.permission.INTERNET",
        "Settings.Secure",
        "getContentResolver(",
    )
    for token in forbidden:
        assert token not in combined


def test_stop_user_service_clears_operation_timeout_before_dropping_operation():
    activity = (JAVA_ROOT / "MainActivity.java").read_text(encoding="utf-8")
    stop = activity.split("private void stopUserService", 1)[1].split(
        "private void renderState", 1
    )[0]
    cleanup = activity.split("private void clearOperationTimeout", 1)[1].split(
        "private void enqueueStaleConnectionRemoval", 1
    )[0]

    assert "clearOperationTimeout(context);" in stop
    assert stop.index("clearOperationTimeout(context);") < stop.index("context.operation = null;")
    assert "mainHandler.removeCallbacks(context.operationTimeout)" in cleanup
    assert "context.operationTimeout = null;" in cleanup
