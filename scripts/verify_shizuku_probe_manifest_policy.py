"""Validate the Shizuku Probe alpha1 APK manifest and its narrowly scoped provider."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
EXPECTED_PACKAGE = "com.mahoraga.shizukuprobe"
EXPECTED_APPLICATION_NAMES = {
    ".ProbeApplication",
    "com.mahoraga.shizukuprobe.ProbeApplication",
}
EXPECTED_ACTIVITY_NAMES = {
    ".MainActivity",
    "com.mahoraga.shizukuprobe.MainActivity",
}
EXPECTED_PROVIDER = "rikka.shizuku.ShizukuProvider"
EXPECTED_PROVIDER_PERMISSION = "android.permission.INTERACT_ACROSS_USERS_FULL"
EXPECTED_PROVIDER_AUTHORITY = "com.mahoraga.shizukuprobe.shizuku"
EXPECTED_QUERY_PACKAGES = {"moe.shizuku.privileged.api"}
FORBIDDEN_COMPONENT_TAGS = {"service", "receiver", "activity-alias"}
MAIN_ACTION = "android.intent.action.MAIN"
LAUNCHER_CATEGORY = "android.intent.category.LAUNCHER"


class ShizukuManifestPolicyError(ValueError):
    """Raised when the Shizuku Probe APK manifest violates alpha1 policy."""


def inspect_manifest(xml_text: str) -> dict[str, object]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ShizukuManifestPolicyError(f"Invalid manifest XML: {exc}") from exc

    violations: list[str] = []
    package = root.get("package")
    if package != EXPECTED_PACKAGE:
        violations.append(f"unexpected package: {package!r}")

    permissions = [
        element.tag for element in root
        if element.tag.startswith("uses-permission")
    ]
    if permissions:
        violations.append(f"manifest must not request Android permissions: {permissions}")

    queries = root.find("queries")
    query_packages = sorted(
        element.get(ANDROID_NS + "name", "")
        for element in (queries.findall("package") if queries is not None else [])
    )
    if set(query_packages) != EXPECTED_QUERY_PACKAGES:
        violations.append(
            f"package visibility must be limited to Shizuku; found {query_packages}"
        )

    app = root.find("application")
    app_children = list(app) if app is not None else []
    if app is None:
        violations.append("application element is missing")
        application_name = None
    else:
        application_name = app.get(ANDROID_NS + "name")
        if application_name not in EXPECTED_APPLICATION_NAMES:
            violations.append(f"unexpected Application class: {application_name!r}")
        if app.get(ANDROID_NS + "allowBackup") != "false":
            violations.append("android:allowBackup must be false")
        if app.get(ANDROID_NS + "usesCleartextTraffic") == "true":
            violations.append("cleartext traffic must not be enabled")

    forbidden = [
        element.tag for element in app_children
        if element.tag in FORBIDDEN_COMPONENT_TAGS
    ]
    if forbidden:
        violations.append(f"background/alias components are forbidden: {forbidden}")

    providers = [element for element in app_children if element.tag == "provider"]
    if len(providers) != 1:
        violations.append(f"expected exactly one provider, found {len(providers)}")
    provider_report: dict[str, object] = {}
    if len(providers) == 1:
        provider = providers[0]
        provider_name = provider.get(ANDROID_NS + "name")
        provider_authority = provider.get(ANDROID_NS + "authorities")
        provider_permission = provider.get(ANDROID_NS + "permission")
        provider_exported = provider.get(ANDROID_NS + "exported")
        provider_enabled = provider.get(ANDROID_NS + "enabled")
        if provider_name != EXPECTED_PROVIDER:
            violations.append(f"unexpected provider: {provider_name!r}")
        if provider_authority != EXPECTED_PROVIDER_AUTHORITY:
            violations.append(f"unexpected provider authority: {provider_authority!r}")
        if provider_permission != EXPECTED_PROVIDER_PERMISSION:
            violations.append(f"provider permission must be {EXPECTED_PROVIDER_PERMISSION!r}")
        if provider_exported != "true" or provider_enabled != "true":
            violations.append("Shizuku provider must be explicitly enabled and exported")
        if provider.get(ANDROID_NS + "multiprocess") != "false":
            violations.append("Shizuku provider must set android:multiprocess=false")
        provider_report = {
            "name": provider_name,
            "authority": provider_authority,
            "permission": provider_permission,
            "exported": provider_exported,
            "enabled": provider_enabled,
        }

    activities = app.findall("activity") if app is not None else []
    launcher_activities = []
    for activity in activities:
        actions = {
            element.get(ANDROID_NS + "name")
            for element in activity.findall("./intent-filter/action")
        }
        categories = {
            element.get(ANDROID_NS + "name")
            for element in activity.findall("./intent-filter/category")
        }
        if MAIN_ACTION in actions and LAUNCHER_CATEGORY in categories:
            launcher_activities.append(activity)

    if len(activities) != 1:
        violations.append(f"expected exactly one Activity, found {len(activities)}")
    if len(launcher_activities) != 1:
        violations.append(
            f"expected exactly one MAIN/LAUNCHER Activity, found {len(launcher_activities)}"
        )
    else:
        activity_name = launcher_activities[0].get(ANDROID_NS + "name")
        if activity_name not in EXPECTED_ACTIVITY_NAMES:
            violations.append(f"unexpected launcher Activity: {activity_name!r}")
        if launcher_activities[0].get(ANDROID_NS + "exported") != "true":
            violations.append("launcher Activity must explicitly set android:exported=true")

    return {
        "package": package,
        "application": application_name,
        "permissions": permissions,
        "forbidden_components": forbidden,
        "query_packages": query_packages,
        "provider_count": len(providers),
        "provider": provider_report,
        "activity_count": len(activities),
        "launcher_activity_count": len(launcher_activities),
        "violations": violations,
        "policy_passed": not violations,
    }


def validate_manifest(xml_text: str) -> dict[str, object]:
    report = inspect_manifest(xml_text)
    if report["violations"]:
        raise ShizukuManifestPolicyError("; ".join(report["violations"]))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_xml", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate_manifest(args.manifest_xml.read_text(encoding="utf-8"))
    except (OSError, ShizukuManifestPolicyError) as exc:
        print(f"Shizuku Probe APK manifest policy failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
