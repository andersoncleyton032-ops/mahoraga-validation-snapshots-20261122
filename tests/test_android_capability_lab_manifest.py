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
