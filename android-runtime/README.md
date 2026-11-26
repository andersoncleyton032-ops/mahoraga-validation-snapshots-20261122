# Mahoraga Android WorkManager bridge

This is a source-only Android bridge. It has **not** been installed, enabled or tested on the Realme device.

## Runtime contract

- WorkManager owns persistent scheduling and rescheduling across ordinary process death and reboot. Android force-stop is different: scheduled work may not resume until the user opens the app again.
- A periodic queue poll uses the 15-minute WorkManager minimum. Timing is inexact and can be deferred by Android, Doze, quotas and OEM power management; this is not an exact alarm or an always-running daemon.
- When Python reports queued work, a fixed explicit broadcast appends a one-shot request to the serialized WorkManager chain.
- The Android worker calls one fixed Termux script. The Python queue lease, one-task scheduler, checkpoint and completion receipt remain authoritative.
- WorkManager has no charging, battery-not-low or storage-not-low hard constraints. The Android request only declares `NetworkType.NOT_REQUIRED`; the Python Governor performs contextual resource admission.
- The Governor selects a smaller `background_companion` budget when the screen is interactive and Mahoraga/Termux is not foreground, and the `background_idle` policy when screen-off conditions are verified. Unknown state fails closed or receives only the minimum budget. Thermal, battery, RAM and storage policies remain dynamic in Python.
- WorkManager's one-shot retry backoff is 120 seconds, above the Python queue's default 90-second lease. This gives an interrupted process's lease time to expire before retry.

## Termux invocation and process bounds

- The bridge invokes only the fixed executable `$PREFIX/bin/timeout`, with SIGTERM at 30 seconds and a 2-second SIGKILL grace period, wrapping the fixed Python executable and `~/mahoraga/scripts/mahoraga_background_worker.py`.
- The bridge waits up to 45 seconds for the Termux result. If the timeout utility is missing or not executable, the bridge fails closed.
- A unique UUID worker identity is generated for each Python invocation. A stale process cannot reuse the logical queue-owner identity of a later invocation.
- The APK does not package the Python worker. The Termux checkout and worker file must match the recorded source commit independently.
- Termux RUN_COMMAND results are accepted only when the internal error code is `Activity.RESULT_OK`, the exit code is zero, a valid worker receipt is present, and original stdout/stderr lengths show that the result was not truncated.
- Each Termux result PendingIntent has a request-specific data URI in addition to its request code, preventing identity collisions when UUID hash codes collide. The result waiter is removed in `finally`, including PendingIntent construction/start failures. Limits are 48 KiB stdout, 16 KiB stderr and 64 KiB combined. The Android worker also enforces an allowlisted set of worker states, exact queue component/version and typed non-negative queue counts, plus consistency between queue.pending and the ordered wake acknowledgement.
- Termux is not a network sandbox. The current allowlisted worker capability does not use network tools, but the Termux process itself retains whatever network access Android grants to Termux.

## Explicit Termux prerequisites

The bridge requires:
1. Termux package `com.termux`, version 0.109 or newer for result PendingIntents.
2. The user to grant this app `com.termux.permission.RUN_COMMAND`.
3. The user to enable `allow-external-apps=true` in Termux.
4. The Termux coreutils `timeout` executable at `$PREFIX/bin/timeout`.

The bridge checks the installed Termux package/version and RUN_COMMAND permission. It does **not** stat or open Termux's private internal storage: Android's app sandbox prevents Mahoraga from inspecting Termux's private files. The fixed `$PREFIX/bin/timeout` path is passed to Termux RUN_COMMAND, and Termux itself determines whether the executable exists and can run. A missing/non-executable timeout is surfaced as a Termux command failure; no broad storage permission or cross-app file access is requested. The `allow-external-apps` property remains a manual Termux prerequisite; a Termux rejection is surfaced as a bridge error. The app does not edit Termux properties, Android settings, battery-optimization settings or permissions. No setup has been performed on a device.

## Android service launch and wake security

- On Android API 26+, the bridge calls `Context.startForegroundService()` to start Termux's `RunCommandService`; older versions use `startService()`.
- Current Termux upstream 0.118.0 declares target SDK 28. Android's Android-12+ cross-app foreground-service background-start restriction applies only when both the caller and service-owning app target API 31+. The Android O background-service launch contract still makes the foreground-service launch API necessary for the Mahoraga caller (target API 36). The bridge checks both installed target SDK values and fails closed if a future Termux version also targets API 31+, pending a revised background-start design.
- The exported wake receiver is required for the Termux process to send an explicit wake broadcast. On Android API 34+, it compares `getSentFromUid()` with the installed Termux package UID. On older Android versions, sender identity cannot be authenticated through this API, so the receiver rejects external wake requests. The 15-minute periodic WorkManager poll remains the fallback; no unauthenticated one-shot wake is accepted. The broadcast is ordered: the receiver returns result code 1 only after WorkManager accepts the one-shot enqueue. The Python adapter requires the exact `Broadcast completed: result=1` acknowledgement; exit code 0 alone is insufficient.
- The bridge does not request INTERNET, microphone, camera, location, storage or overlay permissions. WorkManager may merge its standard scheduling/boot permissions.

## Observability

The Bridge Activity queries WorkManager's one-shot and periodic records and displays state, attempt count, worker status, task ID, wake status, error code and receipt validity when present. The view refreshes when the Activity resumes or when the user requests it.

This is WorkManager-side observability only. It does not yet read the Termux SQLite queue directly or provide a notification channel.

## Stop and validation boundary

Stopping cancels future periodic and one-shot work. A Termux process already started is bounded by the 30-second timeout plus 2-second kill grace; it is not synchronously cancelled by WorkManager's stop button.

Gradle build and CI unit tests validate source compatibility and local policy contracts only. They do not prove that Termux accepts RUN_COMMAND on the installed version, that the wake sender UID is reported as expected, that the Realme firmware honors WorkManager promptly, or that Shizuku/rish observations are available. Those require the explicit device validation plan in `docs/operations/REALME_COMPANION_DEVICE_VALIDATION_PLAN_20261122.md`.

No device installation, permission grant, Termux property change or Android power-policy change is performed by this source tree.

### Source-aware Termux signer trust

The bridge now verifies the installed `com.termux` APK signer before scheduling and again immediately before every RUN_COMMAND dispatch. The policy uses the current signer certificate digest (SHA-256 over the DER certificate), not package name/version alone.

Official release fingerprints are pinned from the Termux upstream `TermuxConstants` source:
- F-Droid: `228FB2CFE90831C1499EC3CCAF61E96E8E1CE70766B9474672CE427334D41C42`
- GitHub release: `B6DA01480EEFD5FBF2CD3771B8D1021EC791304BDD6C4BF41D3FAABAD48EE5E1`
- Google Play: `738F0A30A04D3C8A1BE304AF18D0779BCF3EA88FB60808F657A3521861C2EBF9`
- Termux Devs: `F7A038EB551F1BE8FDF388686B784ABAB4552A5D82DF423E3D8F1B5CBE1C69AE`

On API 28+, the bridge reads `SigningInfo`, rejects multiple signers, and checks the current signer at the end of Android's verified signing-certificate history. Earlier APIs use the legacy single-signature field. Unknown, malformed, unavailable or ambiguous signers fail closed. Debug/test certificates are not trusted. The Activity shows the recognized release channel before it enables scheduling; the worker repeats the check to prevent bypass.

For the currently documented F-Droid installation, the expected channel is **F-Droid**. This code does not inspect Termux's private files, alter `allow-external-apps`, grant permissions or change Android power settings. A physical Realme check is still required to confirm that the installed APK reports the expected official F-Droid signer.

On API levels below 34, the wake receiver rejects external wake requests because sender UID cannot be authenticated. The periodic WorkManager poll remains available. On API 34+, the sender UID must equal the installed Termux UID.


Fingerprint source of record (re-check before changing the allowlist): [Termux upstream TermuxConstants.java](https://github.com/termux/termux-app/blob/master/termux-shared/src/main/java/com/termux/shared/termux/TermuxConstants.java), checked 26/11/2026. The allowlist contains official release-channel certificates only; it intentionally excludes debug/test signing keys.
