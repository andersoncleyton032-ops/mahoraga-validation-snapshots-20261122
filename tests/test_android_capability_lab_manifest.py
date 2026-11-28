from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "android-capability-lab" / "app" / "src" / "main" / "AndroidManifest.xml"
GRADLE = ROOT / "android-capability-lab" / "app" / "build.gradle.kts"
PROBE = ROOT / "android-capability-lab" / "app" / "src" / "main" / "java" / "com" / "mahoraga" / "capabilitylab" / "AndroidCapabilityProbe.java"
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


def test_capability_lab_manifest_requests_no_permissions_or_network():
    root = ET.parse(MANIFEST).getroot()

    permission_tags = [
        child.tag for child in root
        if child.tag in {"uses-permission", "uses-permission-sdk-23", "uses-permission-sdk-m"}
    ]

    assert permission_tags == []
    assert "android.permission.INTERNET" not in MANIFEST.read_text(encoding="utf-8")


def test_capability_lab_declares_no_services_receivers_or_providers():
    root = ET.parse(MANIFEST).getroot()
    application = root.find("application")

    assert application is not None
    component_tags = {child.tag for child in application}
    assert component_tags == {"activity"}


def test_package_visibility_is_explicit_and_allowlisted():
    root = ET.parse(MANIFEST).getroot()
    queries = root.find("queries")

    assert queries is not None
    packages = {
        node.attrib[f"{ANDROID_NS}name"]
        for node in queries.findall("package")
    }
    assert packages == {"com.termux", "moe.shizuku.privileged.api"}


def test_workmanager_is_not_packaged_and_probes_do_not_start_capture_or_binder():
    gradle = GRADLE.read_text(encoding="utf-8")
    probe = PROBE.read_text(encoding="utf-8")

    assert "androidx.work" not in gradle
    for forbidden in (
        "registerListener(",
        "startRecording(",
        "startForegroundService(",
        "bindService(",
        "createVirtualDisplay(",
        "requestPermissions(",
    ):
        assert forbidden not in probe



def test_activity_does_not_request_permissions_or_start_background_work():
    activity = (
        ROOT / "android-capability-lab" / "app" / "src" / "main" / "java"
        / "com" / "mahoraga" / "capabilitylab" / "MainActivity.java"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "requestPermissions(",
        "startService(",
        "startForegroundService(",
        "registerListener(",
        "bindService(",
    ):
        assert forbidden not in activity


def test_camera_x_probe_uses_current_lifecycle_provider_contract():
    probe = PROBE.read_text(encoding="utf-8")

    assert "androidx.camera.lifecycle.ProcessCameraProvider" in probe
    assert "androidx.camera.core.CameraX" not in probe
    assert "Class.forName(CAMERAX_PROVIDER_CLASS, false" in probe


def test_permission_reports_distinguish_manifest_declaration_from_runtime_grant():
    probe = PROBE.read_text(encoding="utf-8")
    state = (
        ROOT / "android-capability-lab" / "app" / "src" / "main" / "java"
        / "com" / "mahoraga" / "capabilitylab" / "CapabilityState.java"
    ).read_text(encoding="utf-8")

    assert "isPermissionDeclared" in probe
    assert "permission_declared" in probe
    assert "permission_granted" in probe
    assert "permissionDeclared" in state
    assert "Status.BLOCKED_BY_MANIFEST" in state


def test_device_resource_snapshot_reports_abi_soc_memory_storage_and_thermal():
    probe = PROBE.read_text(encoding="utf-8")

    for evidence in (
        "Build.SUPPORTED_ABIS",
        "Build.SOC_MODEL",
        "memory.totalMem",
        "storage.getTotalBytes()",
        "storage.getAvailableBytes()",
        "getCurrentThermalStatus()",
        '"status", "not_probed"',
    ):
        assert evidence in probe
    for forbidden in ("registerListener(", "startRecording(", "createVirtualDisplay("):
        assert forbidden not in probe


def test_resource_snapshot_labels_the_scope_of_system_metrics():
    source = PROBE.read_text(encoding="utf-8")
    assert '"processor_count_scope", "runtime_visible_logical_processors"' in source
    assert '"scope", "device_memory"' in source
    assert '"scope", "data_partition"' in source
    assert '"metric", "thermal_status"' in source


def test_activity_only_exposes_the_latest_successful_capability_report():
    activity = (
        ROOT / "android-capability-lab" / "app" / "src" / "main" / "java"
        / "com" / "mahoraga" / "capabilitylab" / "MainActivity.java"
    ).read_text(encoding="utf-8")
    run_probe = activity.split("private void runProbe()", 1)[1].split(
        "private void copyReport()", 1
    )[0]
    copy_report = activity.split("private void copyReport()", 1)[1]

    assert run_probe.index("reportSession.beginCollection()") < run_probe.index(
        "new AndroidCapabilityProbe(this)"
    )
    assert "reportSession.fail()" in run_probe
    assert "reportSession.hasReport()" in copy_report
    assert "reportSession.latestReport()" in copy_report
    assert "latestReport" not in activity
