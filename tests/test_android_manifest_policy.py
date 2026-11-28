from __future__ import annotations

import pytest

from scripts.verify_android_manifest_policy import (
    ManifestPolicyError,
    validate_manifest,
)


ANDROID = "http://schemas.android.com/apk/res/android"


def valid_manifest() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="{ANDROID}" package="com.mahoraga.capabilitylab">
  <queries>
    <package android:name="com.termux" />
    <package android:name="moe.shizuku.privileged.api" />
  </queries>
  <application android:allowBackup="false">
    <activity android:name="com.mahoraga.capabilitylab.MainActivity" android:exported="true">
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
      </intent-filter>
    </activity>
  </application>
</manifest>
"""


def test_accepts_read_only_capability_lab_manifest():
    report = validate_manifest(valid_manifest())

    assert report["policy_passed"] is True
    assert report["permissions"] == []
    assert report["forbidden_components"] == []
    assert report["activity_count"] == 1
    assert report["launcher_activity_count"] == 1


@pytest.mark.parametrize(
    "replacement,expected",
    [
        (
            '<uses-permission android:name="android.permission.INTERNET" />',
            "manifest declares permissions",
        ),
        (
            '<service android:name="com.mahoraga.capabilitylab.BackgroundService" />',
            "background/alias components are forbidden",
        ),
        (
            '<provider android:name="com.mahoraga.capabilitylab.DataProvider" />',
            "background/alias components are forbidden",
        ),
        (
            '<package android:name="com.example.unexpected" />',
            "package visibility must be limited",
        ),
        (
            '<activity android:name="com.mahoraga.capabilitylab.MainActivity" android:exported="false">',
            "launcher Activity must explicitly set",
        ),
        (
            '<activity android:name="com.example.Other" android:exported="true">',
            "unexpected launcher Activity",
        ),
    ],
)
def test_rejects_manifest_policy_violations(replacement, expected):
    xml = valid_manifest()
    if replacement.startswith("<uses-permission"):
        xml = xml.replace("<queries>", replacement + "\n  <queries>")
    elif replacement.startswith("<package"):
        xml = xml.replace(
            '<package android:name="com.termux" />',
            '<package android:name="com.termux" />\n    ' + replacement,
        )
    elif replacement.startswith("<activity"):
        start = '<activity android:name="com.mahoraga.capabilitylab.MainActivity" android:exported="true">'
        xml = xml.replace(start, replacement)
    else:
        xml = xml.replace("<application android:allowBackup=\"false\">",
                          "<application android:allowBackup=\"false\">\n    " + replacement)

    with pytest.raises(ManifestPolicyError, match=expected):
        validate_manifest(xml)


@pytest.mark.parametrize(
    "query_child",
    [
        '<intent><action android:name="android.intent.action.VIEW" /></intent>',
        '<provider android:authorities="com.example.provider" />',
    ],
)
def test_rejects_non_package_queries_that_expand_package_visibility(query_child):
    xml = valid_manifest().replace(
        "</queries>",
        query_child + "\n  </queries>",
    )

    with pytest.raises(ManifestPolicyError, match="queries may contain only package declarations"):
        validate_manifest(xml)


def test_rejects_duplicate_allowlisted_package_entries():
    xml = valid_manifest().replace(
        '<package android:name="com.termux" />',
        '<package android:name="com.termux" />\n    <package android:name="com.termux" />',
    )

    with pytest.raises(ManifestPolicyError, match="exactly one declaration each"):
        validate_manifest(xml)


def test_rejects_duplicate_queries_sections():
    xml = valid_manifest().replace(
        "</queries>",
        "</queries>\n  <queries><package android:name=\"com.termux\" /></queries>",
    )

    with pytest.raises(ManifestPolicyError, match="expected exactly one queries element"):
        validate_manifest(xml)


def test_rejects_non_manifest_xml_root():
    xml = valid_manifest().replace("<manifest ", "<not-manifest ", 1).replace(
        "</manifest>", "</not-manifest>", 1,
    )

    with pytest.raises(ManifestPolicyError, match="unexpected root element"):
        validate_manifest(xml)


def test_rejects_nested_elements_inside_package_query_declarations():
    xml = valid_manifest().replace(
        '<package android:name="com.termux" />',
        '<package android:name="com.termux"><intent /></package>',
    )

    with pytest.raises(
        ManifestPolicyError,
        match="package query declarations must not contain nested elements",
    ):
        validate_manifest(xml)
