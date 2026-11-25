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

The app emits `mahoraga.android_capability_report.v1` with device API metadata and typed capability states:

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
