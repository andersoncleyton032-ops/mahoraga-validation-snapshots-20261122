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
    assert "destroy() = 16777114" in service
    assert "String command" not in service
    assert "String[] args" not in service
    assert "onCompleted(String requestId, int uid, int pid, long elapsedRealtimeMillis)" in callback
    assert "onRejected(String requestId, int reasonCode)" in callback


def test_user_service_checks_shell_uid_and_has_bounded_worker_lifecycle():
    service = (JAVA_ROOT / "UserService.java").read_text(encoding="utf-8")
    assert "Process.myUid()" in service
    assert "uid != 2000" in service
    assert "Executors.newSingleThreadExecutor" in service
    assert "pending.putIfAbsent" in service
    assert "task.cancel(true)" in service
    assert "worker.shutdownNow()" in service
    assert "System.exit(0)" in service


def test_activity_requires_explicit_actions_and_cleans_up_service():
    activity = (JAVA_ROOT / "MainActivity.java").read_text(encoding="utf-8")
    assert 'setText("Iniciar UserService de teste")' in activity
    assert 'setText("Executar prova de identidade")' in activity
    assert 'setText("Cancelar operação")' in activity
    assert 'setText("Encerrar UserService")' in activity
    assert ".daemon(false)" in activity
    assert ".tag(" in activity
    assert ".version(ProbeContract.USER_SERVICE_VERSION)" in activity
    assert "Shizuku.unbindUserService(userServiceArgs, userServiceConnection, true)" in activity
    assert "linkToDeath(userServiceDeathRecipient, 0)" in activity
    assert "ProbeContract.BIND_TIMEOUT_MS" in activity
    assert "ProbeContract.OPERATION_TIMEOUT_MS" in activity
    assert "cleanupExecutor.execute" in activity
    assert "INVALID_OR_LATE_SERVICE_BINDER" in activity


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