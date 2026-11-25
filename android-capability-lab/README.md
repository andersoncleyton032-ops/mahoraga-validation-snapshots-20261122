# Mahoraga Android Capability Lab v0.1

Standalone, read-only Android probe APK. This project is intentionally separate from the Mahoraga Android Companion/WorkManager bridge.

## Build

From this directory, with Android SDK 36 and a compatible Gradle installation:

```bash
gradle :app:testDebugUnitTest
gradle :app:assembleDebug
```

APK output: `app/build/outputs/apk/debug/app-debug.apk`.

No build or device installation has been performed by this commit.

## Probe contract

The app emits `mahoraga.android_capability_report.v1` with device API metadata and typed capability states. The report is an immutable snapshot: nested evidence is defensively copied, capability status/detail fields are validated, unsupported JSON values and non-finite numbers are rejected, and `generated_at` remains stable across serialization:

- `AVAILABLE`
- `REQUIRES_PERMISSION`
- `REQUIRES_USER_ACTION`
- `TEMPORARILY_UNAVAILABLE`
- `UNSUPPORTED`
- `FAILED`

The report is displayed locally and may be copied by the user. It is not uploaded or automatically persisted.

## Read-only boundary

The manifest intentionally requests **no permissions**. It has no INTERNET permission, no camera/microphone/storage/Bluetooth permissions, no foreground service, no receiver and no background worker.

Probes are limited to:
- Android API/build metadata and package presence for Termux and Shizuku;
- sensor metadata inventory, without registering listeners;
- InputManager device metadata, without capturing input events;
- USB device metadata, without opening devices;
- Bluetooth feature/permission state, without enumerating connections when permission is absent;
- camera/microphone feature and permission state, without opening either device;
- CameraX classpath presence, without adding CameraX or starting a preview;
- MediaProjection manager presence, without requesting consent;
- SAF intent resolution, without opening the picker;
- WorkManager library presence and JobScheduler service availability, without initialization or scheduling;
- foreground-service declarations in this APK's own manifest;
- API-level availability of User-Initiated Data Transfer Jobs, without scheduling one;
- Shizuku package presence only; Binder/UserService is not bound in v0.1.

The report explicitly records that no capture, permission request or network upload occurred. A package being installed does not prove that its service is available or authorized. A listed sensor does not prove stable streaming. A resolved intent does not prove a successful user workflow.

## Next increments

1. Add Shizuku API binding and UserService lifecycle probes behind explicit user action.
2. Add WorkManager enqueue/cancel/stop-reason tests in an isolated test application.
3. Add a foreground-service declaration matrix per API level without starting a service.
4. Add optional camera/audio/MediaProjection probes only after explicit user consent and visible foreground UI.
5. Add replayable JSON fixtures and device-side evidence export; no automatic upload.
6. Validate first on emulator, then Realme only after source review and user-approved installation.


## Repository-level contract tests

`tests/test_android_capability_lab_manifest.py` adds four Python tests to the main repository suite. They enforce zero requested permissions/network access, no background components, an explicit Termux/Shizuku package-query allowlist, and absence of WorkManager/capture/Binder APIs in v0.1. These tests are written but not yet executed.


A fifth repository-level Python test also checks that the Activity does not request permissions, start services, register sensor listeners or bind a service. Total Android Lab tests written: four JVM + five Python contract tests; execution pending.


## Build evidence

Curated public run #45554778537 completed `:app:testDebugUnitTest` and `:app:assembleDebug` successfully. The resulting debug APK was 880,806 bytes with SHA-256 `4feca45bdab5a9b872b609f53ad6ce238f80bd550548955a3f08ac799f100782`. The binary manifest was inspected: no permissions, services, receivers or providers; package visibility is limited to Termux and Shizuku. The APK was not installed on a device.


## Latest full validation run — 25/11/2026

Public mirror PR #17 / run #45555686041 completed all three jobs successfully:
- Python 3.12: 105 passed in 0.52s.
- Python 3.14: 105 passed in 0.38s.
- Android: `:app:testDebugUnitTest` and `:app:assembleDebug` completed; Gradle reported BUILD SUCCESSFUL in 1m 20s.

Latest APK artifact ID: `14996145941`; archive digest: `sha256:29923cf0abeef680a8280325dfa37db83622ee70f6196197bf5bdef32763ccfb`; APK size: 880,806 bytes; APK SHA-256: `bb67c352252e882d5ac752e19f8c5607ff09a77e53b19d8133ea58e3ef8f63d1`.

The latest APK was downloaded, checksum re-computed and matched. Its binary manifest was parsed again: no uses-permission, service, receiver or provider elements; only Termux and Shizuku package-visibility entries. No device installation or runtime claim.

The report contract was subsequently hardened with deep immutability and JSON/status validation. Four additional JVM tests were added (eight JVM + five Python total). The earlier curated build evidence predates this refinement; rerun the Android workflow before treating the revised APK as validated.


The current report contract also rejects cyclic or excessively nested evidence and non-string object keys. Current test inventory: 11 JVM tests and 5 Python contract tests. The prior public build predates these seven additional JVM tests; current revision remains unvalidated until a new Gradle run.
