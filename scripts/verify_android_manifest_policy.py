"""Validate the final APK manifest against the read-only Capability Lab v0.1 policy."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
EXPECTED_PACKAGE = "com.mahoraga.capabilitylab"
EXPECTED_QUERY_PACKAGES = {
    "com.termux",
    "moe.shizuku.privileged.api",
}
FORBIDDEN_COMPONENT_TAGS = {"service", "receiver", "provider", "activity-alias"}
MAIN_ACTION = "android.intent.action.MAIN"
LAUNCHER_CATEGORY = "android.intent.category.LAUNCHER"


class ManifestPolicyError(ValueError):
    """Raised when an APK manifest violates the v0.1 read-only policy."""


def inspect_manifest(xml_text: str) -> dict[str, object]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ManifestPolicyError(f"Invalid manifest XML: {exc}") from exc

    violations: list[str] = []
    package = root.get("package")
    if package != EXPECTED_PACKAGE:
        violations.append(f"unexpected package: {package!r}")

    permissions = [
        element.tag
        for element in root
        if element.tag.startswith("uses-permission")
    ]
    if permissions:
        violations.append(f"manifest declares permissions: {permissions}")

    app = root.find("application")
    if app is None:
        violations.append("application element is missing")
        app_children = []
    else:
        app_children = list(app)
        forbidden = [
            element.tag
            for element in app_children
            if element.tag in FORBIDDEN_COMPONENT_TAGS
        ]
        if forbidden:
            violations.append(f"background/alias components are forbidden: {forbidden}")
        if app.get(ANDROID_NS + "allowBackup") != "false":
            violations.append("android:allowBackup must be false")
        if app.get(ANDROID_NS + "usesCleartextTraffic") == "true":
            violations.append("cleartext traffic must not be enabled")

    queries = root.find("queries")
    query_entries = list(queries) if queries is not None else []
    non_package_queries = [
        element.tag for element in query_entries if element.tag != "package"
    ]
    if non_package_queries:
        violations.append(
            "only explicit package queries are allowed; "
            f"found {non_package_queries}"
        )
    if any(list(element) for element in query_entries):
        violations.append("package query entries must not contain nested elements")

    query_packages = sorted(
        element.get(ANDROID_NS + "name", "")
        for element in (queries.findall("package") if queries is not None else [])
    )
    if set(query_packages) != EXPECTED_QUERY_PACKAGES:
        violations.append(
            "package visibility must be limited to Termux and Shizuku; "
            f"found {query_packages}"
        )

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
        launcher_name = launcher_activities[0].get(ANDROID_NS + "name")
        if launcher_name not in {
            ".MainActivity",
            "com.mahoraga.capabilitylab.MainActivity",
        }:
            violations.append(f"unexpected launcher Activity: {launcher_name!r}")
        if launcher_activities[0].get(ANDROID_NS + "exported") != "true":
            violations.append("launcher Activity must explicitly set android:exported=true")

    return {
        "package": package,
        "permissions": permissions,
        "forbidden_components": [
            element.tag for element in app_children
            if element.tag in FORBIDDEN_COMPONENT_TAGS
        ],
        "query_packages": query_packages,
        "query_entry_types": [element.tag for element in query_entries],
        "activity_count": len(activities),
        "launcher_activity_count": len(launcher_activities),
        "violations": violations,
        "policy_passed": not violations,
    }


def validate_manifest(xml_text: str) -> dict[str, object]:
    report = inspect_manifest(xml_text)
    if report["violations"]:
        raise ManifestPolicyError("; ".join(report["violations"]))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_xml", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate_manifest(args.manifest_xml.read_text(encoding="utf-8"))
    except (OSError, ManifestPolicyError) as exc:
        print(f"APK manifest policy failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
