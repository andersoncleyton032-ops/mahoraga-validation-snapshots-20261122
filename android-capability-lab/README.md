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

`tests/test_android_capability_lab_manifest.py` adds four Python tests to the main repository suite. They enforce zero requested permissions/network access, no background components, an explicit Termux/Shizuku package-query allowlist, and absence of WorkManager/capture/Binder APIs in v0.1. These five Python contracts were included in the public 122-test Python matrix and passed.


A fifth repository-level Python test also checks that the Activity does not request permissions, start services, register sensor listeners or bind a service. Total Android Lab tests written: thirteen JVM + five Python contract tests; execution pending.


## Build evidence

Curated public run #45554778537 completed `:app:testDebugUnitTest` and `:app:assembleDebug` successfully. The resulting debug APK was 880,806 bytes with SHA-256 `4feca45bdab5a9b872b609f53ad6ce238f80bd550548955a3f08ac799f100782`. The binary manifest was inspected: no permissions, services, receivers or providers; package visibility is limited to Termux and Shizuku. The APK was not installed on a device.


## Latest full validation run — 25/11/2026

Public mirror PR #17 / run #45555686041 completed all three jobs successfully:
- Python 3.12: 105 passed in 0.52s.
- Python 3.14: 105 passed in 0.38s.
- Android: `:app:testDebugUnitTest` and `:app:assembleDebug` completed; Gradle reported BUILD SUCCESSFUL in 1m 20s.

Latest APK artifact ID: `14996145941`; archive digest: `sha256:29923cf0abeef680a8280325dfa37db83622ee70f6196197bf5bdef32763ccfb`; APK size: 880,806 bytes; APK SHA-256: `bb67c352252e882d5ac752e19f8c5607ff09a77e53b19d8133ea58e3ef8f63d1`.

The latest APK was downloaded, checksum re-computed and matched. Its binary manifest was parsed again: no uses-permission, service, receiver or provider elements; only Termux and Shizuku package-visibility entries. No device installation or runtime claim.

The report contract was subsequently hardened with deep immutability and JSON/status validation. Nine additional JVM tests were added (thirteen JVM + five Python total). The current revision is validated by public run #45600075401: 13/13 JVM tests passed, Gradle build succeeded, and the APK manifest policy gate passed.


The current report contract also rejects cyclic or excessively nested evidence and non-string object keys. Current test inventory: 13 JVM tests and 5 Python contract tests. Public run #45600075401 validates the current revision: 13 JVM tests passed and the Gradle build succeeded.


## Execução comprovada — 25/11/2026

Validação pública curada PR #17, run `45598848336`, usando os arquivos Android atuais:
- Python 3.12: 109 passed.
- Python 3.14: 109 passed.
- `:app:testDebugUnitTest`: task concluída com sucesso.
- `:app:assembleDebug`: BUILD SUCCESSFUL.
- APK artifact ID `15013849984`; SHA-256 do APK `5a7bac490befd0368d402c38521fd5ea561e33e8e23ee24715e3f379cbb4ba45`.
- O binário `AndroidManifest.xml` extraído do APK foi analisado: zero tags `uses-permission`, zero serviços/receivers/providers; apenas visibilidade de pacote para Termux e Shizuku e a Activity launcher.
- O arquivo de teste contém 13 métodos `@Test`; o Gradle test task passou. Este run não publicou XML JUnit, portanto a contagem de testes executados ainda não foi confirmada por relatório XML. O workflow foi atualizado para publicar esses relatórios em execuções futuras.
- Nenhum APK foi instalado; nenhuma validação no Realme foi realizada.

The Android workflow now also summarizes and uploads JUnit XML test reports, so subsequent runs can confirm the exact JVM test count rather than relying only on task success.


## Validação final do snapshot público — run #45600075401

- Python 3.12: 122 passed; Python 3.14: 122 passed.
- JUnit XML: 13 tests, 0 skipped, 0 failures, 0 errors.
- `:app:testDebugUnitTest` e `:app:assembleDebug`: BUILD SUCCESSFUL.
- `verify_android_manifest_policy.py`: `policy_passed=true`; zero permissões, zero services/receivers/providers/aliases, allowlist de queries Termux/Shizuku e launcher Activity única.
- JUnit artifact #15014814219.
- APK artifact #15016035633; SHA-256 `6416799bdbf977b8c5bfc04111c6ec5ec9f0f1bce1a7dff0d224c79f8936c921`.
- O workflow usa `retry_gradle.py` para 429/5xx transitórios e agora publica JUnit XML.
- Nenhum APK foi instalado e o Realme não foi validado em runtime.
- O runner privado continua bloqueado antes dos steps (run #45600387211); a evidência de build vem do snapshot público isolado.


### Precisão do inventário (v0.1.1)

O relatório inclui ABI, SoC quando a API oferece o campo, número de processadores, RAM, armazenamento e estado térmico quando disponível. GPU permanece `NOT_PROBED`. Para câmera, microfone e Bluetooth, o estado de permissão diferencia declaração no manifesto e concessão runtime; nenhuma permissão é solicitada nesta versão. O probe CameraX verifica `ProcessCameraProvider`, sem inicializar a câmera.


Resource metric semantics are explicit: processor count means logical processors visible to the app runtime; RAM values describe device-wide memory; storage values describe the internal data partition; thermal data is a PowerManager thermal status, not a direct temperature measurement. GPU remains unmeasured.
