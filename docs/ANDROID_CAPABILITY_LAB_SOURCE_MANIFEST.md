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

`CapabilityReport` now recursively copies and freezes nested maps/lists, validates capability status against the enum, requires non-empty detail, rejects non-JSON values and non-finite numbers, and fixes `generated_at` at construction time. The JVM suite increased from four to eleven tests.

The previous public run `45555686041` validated the earlier four-test Android revision. The four new JVM tests and rebuilt APK have **not** yet been executed. The current public PR head was updated through the repository connector, but no workflow run is associated with that new head; do not carry forward the previous build result as evidence for this revision.


The latest source also rejects cyclic evidence, nesting beyond 32 levels, more than 50,000 JSON nodes, and non-string keys. Current Android suite: 13 JVM tests + 5 Python contracts; nine JVM tests were added after the last successful public Gradle run. Current revision remains unvalidated.


Final test inventory correction: 13 JVM tests + 5 Python contracts. Nine JVM tests were added after the last successful public Gradle run; current revision is still pending execution.


Latest source checkpoints: CapabilityReport code `9290fffffb49fb4ce8ae263281c8846cfff6e3d9`; JVM tests `3fe5b0ae9d570dfcc1d418ae83bcd2d61e665107`. Both source files are byte-identical to private PR #275. Current inventory: 13 JVM + 5 Python contracts. No workflow run exists for current public head `17e45ae71786ffab5e8781b4731197502732a0b8`; do not claim current tests/build passed.


## Final public validation — run #45600075401

- Python 3.12 and 3.14: 122/122 passed each.
- Android JUnit report artifact #15014814219: 13 tests, 0 skipped, 0 failures, 0 errors.
- Gradle `:app:testDebugUnitTest` and `:app:assembleDebug`: BUILD SUCCESSFUL.
- Built APK manifest policy: passed. No permissions, services, receivers, providers or activity aliases; Termux/Shizuku query allowlist; single exported launcher Activity; backups disabled.
- APK artifact #15016035633; SHA-256 `6416799bdbf977b8c5bfc04111c6ec5ec9f0f1bce1a7dff0d224c79f8936c921`.
- Retry helper and manifest policy helper are now part of the source snapshot and their Python tests are included in the 122-test matrix.
- No installation or Realme runtime validation.


## Shizuku Probe v0.2-alpha1 — public validation run #45602931133

- Separate module: `android-shizuku-probe`, package `com.mahoraga.shizukuprobe`, version `0.2.0-alpha1`.
- Shizuku API/provider 13.1.5; Shizuku app release observed at 13.6.0. Version skew is documented and Android 16 runtime compatibility remains unproven.
- Python matrix: 132 passed on Python 3.12 and 3.14.
- Shizuku JVM tests: 8/8, 0 skipped/failures/errors; JUnit artifact #15016771464.
- Shizuku Gradle test and APK assembly: BUILD SUCCESSFUL.
- APK manifest policy: passed. The only merged `uses-permission` is the Shizuku-specific runtime permission `moe.shizuku.manager.permission.API_V23` contributed by the official provider AAR. The provider is `rikka.shizuku.ShizukuProvider`, protected by `android.permission.INTERACT_ACROSS_USERS_FULL`; package visibility is limited to Shizuku; no background services/receivers/aliases; Sui auto-initialization is disabled.
- APK artifact #15016252268; SHA-256 `1826eb3c47fbff64e3caf04f1cc0370af59795a0506583aedf5a015c06f45a40`.
- Device installation and Binder/permission/UID 2000 runtime validation are still pending. Do not start alpha2 UserService before that evidence.
- Manual test protocol: `docs/testing/SHIZUKU_PROBE_ALPHA1_DEVICE_TEST.md`.
