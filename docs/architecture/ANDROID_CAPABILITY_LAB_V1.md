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

The report records Android build/API metadata, package visibility for Termux and Shizuku, sensor metadata, InputManager devices, USB device metadata, Bluetooth feature/permission state, camera/microphone feature and permission state, CameraX classpath presence, MediaProjection service presence, SAF intent resolution, WorkManager classpath presence, JobScheduler service, this APK's own foreground-service declarations and API-level UIDT availability. `CapabilityReport` validates every capability status against the typed enum, requires a non-empty detail, rejects non-JSON/non-finite evidence, deep-copies nested maps/lists and exposes immutable nested snapshots. Its timestamp is fixed at collection construction, so repeated serialization does not rewrite the observation time. Recursive validation rejects cycles, non-string object keys, nesting beyond 32 levels and more than 50,000 JSON nodes across the complete report.

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

The dedicated workflow `.github/workflows/android-capability-lab.yml` runs both commands when the module changes or by manual dispatch. Thirteen JVM tests cover the capability-state classifier, report immutability, stable timestamps, JSON compatibility and malformed status/detail rejection. Build and tests have not been executed: the first Actions run failed before steps and its job logs were unavailable (`BlobNotFound`).

## Follow-up sequence

1. Obtain a runner that starts steps; build and run the JVM tests.
2. Inspect merged manifest and APK contents to verify zero permissions, services and receivers.
3. Run on an emulator and verify the report schema and probe failure handling.
4. Add Shizuku Binder/UserService binding as a separate explicit user-triggered experiment with lifecycle cleanup and permission-state reporting.
5. Add WorkManager scheduling/cancel/stop-reason probes in a separately reviewed increment.
6. Add camera/audio/MediaProjection probes only after a visible consent flow and permission-specific module review.
7. Install on the Realme only after build, manifest and emulator evidence are reviewed and the user explicitly authorizes device installation.


The repository also contains `tests/test_android_capability_lab_manifest.py` with four Python contract tests. They verify that the manifest requests no permissions, declares no background components, exposes only the two explicit package queries, and that the v0.1 probe does not package WorkManager or invoke capture/Binder APIs. Together with thirteen JVM tests and five Python contracts, sixteen tests are written; none has execution evidence yet.


A fifth Python contract test additionally verifies that the Activity does not request permissions, start services, register sensor listeners or bind services. Total Android Lab tests now written: sixteen (thirteen JVM + five Python). The earlier curated run validated the previous four-JVM-test version; the eleven-test refinement has not yet been executed.


## Build evidence — curated public runner

A public curated validation run completed both `:app:testDebugUnitTest` and `:app:assembleDebug` successfully on Android API 36 / JDK 17 / Gradle 9.6.0 (run #45554778537). The Android job concluded success. The APK artifact was downloaded and inspected locally:

- Artifact ID: `14995830821`, archive size 873,710 bytes.
- APK size: 880,806 bytes.
- SHA-256: `4feca45bdab5a9b872b609f53ad6ce238f80bd550548955a3f08ac799f100782`.
- Binary AndroidManifest.xml parsed from the APK: elements were manifest, uses-sdk, queries, two package entries, application, activity, intent-filter, action and category. No uses-permission, service, receiver or provider elements were present.
- The only package visibility entries were `com.termux` and `moe.shizuku.privileged.api`.

The foreground-service probe uses the public `ServiceInfo.getForegroundServiceType()` API on API 29+, guarded by SDK level. No APK was installed. This proves build/unit-test task completion and manifest structure for the curated snapshot, not runtime behavior on emulator or Realme.


## Latest full validation run — 25/11/2026

Public mirror PR #17 / run #45555686041 completed all three jobs successfully:
- Python 3.12: 105 passed in 0.52s.
- Python 3.14: 105 passed in 0.38s.
- Android: `:app:testDebugUnitTest` and `:app:assembleDebug` completed; Gradle reported BUILD SUCCESSFUL in 1m 20s.

Latest APK artifact ID: `14996145941`; archive digest: `sha256:29923cf0abeef680a8280325dfa37db83622ee70f6196197bf5bdef32763ccfb`; APK size: 880,806 bytes; APK SHA-256: `bb67c352252e882d5ac752e19f8c5607ff09a77e53b19d8133ea58e3ef8f63d1`.

The latest APK was downloaded, checksum re-computed and matched. Its binary manifest was parsed again: no uses-permission, service, receiver or provider elements; only Termux and Shizuku package-visibility entries. No device installation or runtime claim.
