# Android Capability Lab — source manifest

## Private source lineage
- Private repository: `andersoncleyton032-ops/mahoraga-core`.
- Source PR: #273, Draft, branch `implementation/android-capability-lab-20261125`.
- Private source head at import: `92d2a455ac2799feb7973b0f00f814768c2d0b15`.
- Public validation branch: `validation/android-capability-lab-main-20261125`.
- Public base: `main` at `3d834e0a8177eca30578fbb7baacd6be5eb82ae5`.

## Selected files
- Standalone Android project: `android-capability-lab/**`.
- Python manifest contract tests: `tests/test_android_capability_lab_manifest.py`.
- Technical contract: `docs/architecture/ANDROID_CAPABILITY_LAB_V1.md`.
- Curated Python workflow extended with Android build/test job: `.github/workflows/snapshot-tests.yml`.

## Review and exclusions
- Manifest has no requested permissions, INTERNET permission, service, receiver or worker. Unused WorkManager dependency was removed before import.
- Shizuku is detected only by package presence; Binder/UserService is not bound. No camera, microphone, MediaProjection, sensor listener, input event capture, USB open, Bluetooth connection enumeration, job scheduling, permission request or network upload occurs.
- Report includes only ordinary Android build metadata (manufacturer/model/device/API); no serial, account identifier, location, private path, credential, local database, continuity/handoff/audit log, model, dataset or artifact is included.
- Tests are synthetic and generic. No personal or device-specific fixture is copied.
- This curated PR validates only the selected Android Capability Lab and its manifest contract. It does not validate the private visual 90-test suite or full-system integration.
- Build/test evidence must be recorded against the exact resulting public snapshot head. No APK is installed on a device.


A fifth Python contract test verifies the Activity does not request permissions, start services, register sensor listeners or bind services. Total tests in this selected snapshot: four JVM + five Python contract tests.


## Build workflow correction (25/11/2026)

- Updated private source head for Gradle configuration: `93d0f8c325b7564a897ddd3d8176abed2f91fa2f`.
- Removed `unitTests.returnDefaultValues` from the AGP 9.5.2 Kotlin DSL because the configured DSL does not expose that property; the four JVM tests use pure Java logic and do not need Android stub defaults.
- Replaced the incompatible `android-actions/setup-android@v3` step with direct use of the runner's preinstalled `sdkmanager`; license acceptance and API 36 installation succeeded in run #45554159248.


## Subsequent report-contract hardening — 25/11/2026

The current source was refreshed from private PR #275, branch `implementation/android-capability-lab-20261125-final`, code HEAD `39adf07e2b3aab07d499fb47020539768706a205`.

`CapabilityReport` now recursively copies and freezes nested maps/lists, validates capability status against the enum, requires non-empty detail, rejects non-JSON values and non-finite numbers, and fixes `generated_at` at construction time. The JVM suite increased from four to eight tests.

The previous public run `45555686041` validated the earlier four-test Android revision. The four new JVM tests and rebuilt APK have **not** yet been executed. The current public PR head was updated through the repository connector, but no workflow run is associated with that new head; do not carry forward the previous build result as evidence for this revision.
