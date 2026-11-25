# Android Capability Lab v0.1 — contrato e limites

**Module:** `android-capability-lab/`  
**Application ID:** `com.mahoraga.capabilitylab`  
**Report schema:** `mahoraga.android_capability_report.v1`  
**Status:** SOURCE_IMPLEMENTED / TESTS_ADDED / BUILD_NOT_EXECUTED / DEVICE_NOT_VALIDATED

## Separation

This is a standalone diagnostic APK, separate from the Android Companion/WorkManager bridge. It has no Python bridge, Shizuku client binding, background worker, service, receiver or network client.

The manifest intentionally has no `uses-permission` declarations and no `INTERNET` permission. WorkManager is not packaged in v0.1 because its unused dependency would add unrelated manifest surface. JobScheduler is probed through the platform API; WorkManager is reported as not linked until a later controlled increment.

## Report contract

Each capability entry contains a typed state, a human-readable detail and optional evidence. States are:

- `AVAILABLE`: the API/feature/package was positively observed.
- `REQUIRES_PERMISSION`: the feature exists but the relevant runtime permission is not granted. The current APK does not request it.
- `REQUIRES_USER_ACTION`: explicit user consent or a separate action is needed.
- `TEMPORARILY_UNAVAILABLE`: package/SDK component is not present or not linked in this build; this does not prove permanent unsupported status.
- `UNSUPPORTED`: the device/platform reports the feature is absent.
- `FAILED`: the probe could not obtain reliable evidence.

The report records Android build/API metadata, package visibility for Termux and Shizuku, sensor metadata, InputManager devices, USB device metadata, Bluetooth feature/permission state, camera/microphone feature and permission state, CameraX classpath presence, MediaProjection service presence, SAF intent resolution, WorkManager classpath presence, JobScheduler service, this APK's own foreground-service declarations and API-level UIDT availability.

## Read-only guarantees

v0.1 performs only metadata queries. It does not:
- register sensor listeners or sample sensor values;
- capture GameSir/gamepad events;
- open USB/Bluetooth devices or enumerate Bluetooth connections without permission;
- open camera or microphone;
- start AudioRecord, CameraX, MediaProjection or a foreground service;
- bind Shizuku Binder or start UserService;
- initialize WorkManager, enqueue/cancel jobs or inspect another app's jobs;
- launch SAF picker;
- request or change Android permissions/settings;
- persist a device journal or upload data.

The user explicitly presses the inventory button. The report remains in the Activity and can be copied to the clipboard. No automatic file export or network transmission exists.

## Build and unit tests

From this directory, with Android SDK platform 36 and a compatible Gradle distribution:

```bash
gradle :app:testDebugUnitTest
gradle :app:assembleDebug
```

The dedicated workflow `.github/workflows/android-capability-lab.yml` runs both commands when the module changes or by manual dispatch. Four JVM tests currently cover the capability-state classifier. Build and tests have not been executed: the first Actions run failed before steps and its job logs were unavailable (`BlobNotFound`).

## Follow-up sequence

1. Obtain a runner that starts steps; build and run the JVM tests.
2. Inspect merged manifest and APK contents to verify zero permissions, services and receivers.
3. Run on an emulator and verify the report schema and probe failure handling.
4. Add Shizuku Binder/UserService binding as a separate explicit user-triggered experiment with lifecycle cleanup and permission-state reporting.
5. Add WorkManager scheduling/cancel/stop-reason probes in a separately reviewed increment.
6. Add camera/audio/MediaProjection probes only after a visible consent flow and permission-specific module review.
7. Install on the Realme only after build, manifest and emulator evidence are reviewed and the user explicitly authorizes device installation.


The repository also contains `tests/test_android_capability_lab_manifest.py` with four Python contract tests. They verify that the manifest requests no permissions, declares no background components, exposes only the two explicit package queries, and that the v0.1 probe does not package WorkManager or invoke capture/Binder APIs. Together with four JVM classifier tests, eight tests are written; none has execution evidence yet.
