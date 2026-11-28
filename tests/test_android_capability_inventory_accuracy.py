from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "android-capability-lab/app/src/main/java/com/mahoraga/capabilitylab/AndroidCapabilityProbe.java"
STATE = ROOT / "android-capability-lab/app/src/main/java/com/mahoraga/capabilitylab/CapabilityState.java"


def test_camerax_probe_uses_current_process_camera_provider_contract():
    source = PROBE.read_text(encoding="utf-8")
    assert "androidx.camera.lifecycle.ProcessCameraProvider" in source
    assert "androidx.camera.core.CameraX" not in source
    assert "Class.forName(CAMERAX_PROVIDER_CLASS, false" in source


def test_permission_evidence_distinguishes_manifest_declaration_and_grant():
    source = PROBE.read_text(encoding="utf-8")
    state = STATE.read_text(encoding="utf-8")
    assert "isPermissionDeclared" in source
    assert "permission_declared" in source
    assert "permission_granted" in source
    assert "permissionDeclared" in state
    assert "Status.BLOCKED_BY_MANIFEST" in state


def test_resource_inventory_is_read_only_and_explicit_about_unknown_gpu():
    source = PROBE.read_text(encoding="utf-8")
    for token in (
        "Build.SUPPORTED_ABIS",
        "Build.SOC_MODEL",
        "memory.totalMem",
        "storage.getTotalBytes()",
        "storage.getAvailableBytes()",
        "getCurrentThermalStatus()",
        '"status", "not_probed"',
    ):
        assert token in source
    for forbidden in ("registerListener(", "startRecording(", "createVirtualDisplay("):
        assert forbidden not in source


def test_resource_snapshot_labels_the_scope_of_system_metrics():
    source = PROBE.read_text(encoding="utf-8")
    assert '"processor_count_scope", "runtime_visible_logical_processors"' in source
    assert '"scope", "device_memory"' in source
    assert '"scope", "data_partition"' in source
    assert '"metric", "thermal_status"' in source
