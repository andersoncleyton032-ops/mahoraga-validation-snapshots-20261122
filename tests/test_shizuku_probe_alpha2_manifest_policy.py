from __future__ import annotations

import pytest

from scripts.verify_shizuku_probe_alpha2_manifest_policy import (
    ShizukuAlpha2ManifestPolicyError,
    validate_manifest,
)

ANDROID = "http://schemas.android.com/apk/res/android"


def valid_manifest() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="{ANDROID}"
    package="com.mahoraga.shizukuprobe"
    android:versionName="0.2.0-alpha2">
  <uses-permission android:name="moe.shizuku.manager.permission.API_V23" />
  <queries>
    <package android:name="moe.shizuku.privileged.api" />
  </queries>
  <application android:name=".ProbeApplication" android:allowBackup="false">
    <provider
      android:name="rikka.shizuku.ShizukuProvider"
      android:authorities="com.mahoraga.shizukuprobe.shizuku"
      android:multiprocess="false"
      android:enabled="true"
      android:exported="true"
      android:permission="android.permission.INTERACT_ACROSS_USERS_FULL" />
    <activity android:name=".MainActivity" android:exported="true">
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
      </intent-filter>
    </activity>
  </application>
</manifest>
"""


def test_accepts_alpha2_manifest_with_only_shizuku_permission_and_provider():
    report = validate_manifest(valid_manifest())
    assert report["policy_passed"] is True
    assert report["versionName"] == "0.2.0-alpha2"
    assert report["permissions"] == ["moe.shizuku.manager.permission.API_V23"]
    assert report["forbidden_components"] == []
    assert report["activity_count"] == 1
    assert report["provider_count"] == 1


@pytest.mark.parametrize(
    "replacement,expected",
    [
        (
            '<uses-permission android:name="android.permission.INTERNET" />',
            "uses-permission must be limited",
        ),
        (
            'android:versionName="0.2.0-alpha1"',
            "unexpected versionName",
        ),
        (
            '<service android:name="com.mahoraga.shizukuprobe.BackgroundService" />',
            "background/alias components are forbidden",
        ),
        (
            '<package android:name="com.example.unexpected" />',
            "package visibility must be limited",
        ),
    ],
)
def test_rejects_alpha2_manifest_policy_violations(replacement, expected):
    xml = valid_manifest()
    if replacement.startswith("<uses-permission"):
        xml = xml.replace("<queries>", replacement + "\n  <queries>")
    elif replacement.startswith("<package"):
        xml = xml.replace(
            '<package android:name="moe.shizuku.privileged.api" />',
            '<package android:name="moe.shizuku.privileged.api" />\n    ' + replacement,
        )
    elif replacement.startswith("<service"):
        xml = xml.replace(
            'android:allowBackup="false">',
            'android:allowBackup="false">\n    ' + replacement,
        )
    else:
        xml = xml.replace('android:versionName="0.2.0-alpha2"', replacement)
    with pytest.raises(ShizukuAlpha2ManifestPolicyError, match=expected):
        validate_manifest(xml)