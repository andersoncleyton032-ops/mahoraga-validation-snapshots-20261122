from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_shizuku_probe_manifest_policy import (
    ShizukuManifestPolicyError,
    validate_manifest,
)

ANDROID = "http://schemas.android.com/apk/res/android"


def valid_manifest() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="{ANDROID}" package="com.mahoraga.shizukuprobe">
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


def test_accepts_only_the_expected_shizuku_provider_and_launcher():
    report = validate_manifest(valid_manifest())
    assert report["policy_passed"] is True
    assert report["permissions"] == []
    assert report["forbidden_components"] == []
    assert report["provider_count"] == 1
    assert report["activity_count"] == 1


@pytest.mark.parametrize(
    "replacement,expected",
    [
        (
            '<uses-permission android:name="android.permission.INTERNET" />',
            "manifest must not request Android permissions",
        ),
        (
            '<package android:name="com.example.unexpected" />',
            "package visibility must be limited to Shizuku",
        ),
        (
            '<service android:name="com.mahoraga.shizukuprobe.BackgroundService" />',
            "background/alias components are forbidden",
        ),
        (
            '<provider android:name="com.example.OtherProvider" />',
            "expected exactly one provider",
        ),
        (
            '<activity android:name=".MainActivity" android:exported="false">',
            "launcher Activity must explicitly set",
        ),
        (
            'android:permission="android.permission.INTERACT_ACROSS_USERS"',
            "provider permission must be",
        ),
        (
            'android:authorities="com.example.other"',
            "unexpected provider authority",
        ),
        (
            'android:name=".OtherApplication"',
            "unexpected Application class",
        ),
    ],
)
def test_rejects_shizuku_manifest_policy_violations(replacement, expected):
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
            '<application android:name=".ProbeApplication" android:allowBackup="false">',
            '<application android:name=".ProbeApplication" android:allowBackup="false">\n    ' + replacement,
        )
    elif replacement.startswith("<provider"):
        xml = xml.replace(
            '    <provider\n',
            '    <provider\n' + replacement + "\n    <provider\n",
        )
    elif replacement.startswith("<activity"):
        xml = xml.replace(
            '<activity android:name=".MainActivity" android:exported="true">',
            replacement,
        )
    elif replacement.startswith('android:permission='):
        xml = xml.replace(
            'android:permission="android.permission.INTERACT_ACROSS_USERS_FULL"',
            replacement,
        )
    elif replacement.startswith('android:authorities='):
        xml = xml.replace(
            'android:authorities="com.mahoraga.shizukuprobe.shizuku"',
            replacement,
        )
    else:
        xml = xml.replace(
            'android:name=".ProbeApplication"',
            replacement,
        )

    with pytest.raises(ShizukuManifestPolicyError, match=expected):
        validate_manifest(xml)


def test_probe_application_disables_automatic_sui_initialization():
    source = Path(
        "android-shizuku-probe/app/src/main/java/com/mahoraga/shizukuprobe/ProbeApplication.java"
    ).read_text(encoding="utf-8")
    assert "ShizukuProvider.disableAutomaticSuiInitialization();" in source
