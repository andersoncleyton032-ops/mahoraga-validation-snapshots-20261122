# Mahoraga Android WorkManager bridge

This is a source-only Android bridge. It has **not** been installed, enabled or tested on the Realme device.

## Runtime contract

- WorkManager owns persistent scheduling and rescheduling across ordinary process death and reboot.
- A periodic queue poll runs no more often than the 15-minute WorkManager minimum.
- When Python reports queued work, a fixed explicit broadcast appends a one-shot request to the serialized WorkManager chain.
- One invocation calls one fixed Termux script. The Python queue lease, one-task scheduler and completion receipt remain authoritative.
- WorkManager constraints require charging, battery-not-low and storage-not-low. Network is explicitly not required.
- The Python Governor selects Companion when the screen is interactive and Mahoraga/Termux is not foreground; otherwise it selects the screen-off idle policy. Unknown state fails closed.
- WorkManager timing is inexact and can be deferred by Android, Doze, quotas and OEM power management. It is not an exact alarm or an always-running daemon.

## Explicit Termux prerequisites

The bridge requires:
1. Termux package `com.termux`, version 0.109 or newer for result PendingIntents.
2. The user to grant this app `com.termux.permission.RUN_COMMAND`.
3. The user to enable `allow-external-apps=true` in Termux.

The app only displays these requirements. It does not edit Termux properties, Android settings, battery-optimization settings or permissions. No setup has been performed on a device.

The bridge invokes only `$PREFIX/bin/python` with the fixed script `~/mahoraga/scripts/mahoraga_background_worker.py`. It does not accept arbitrary command paths, shell fragments or task arguments. The Python wake adapter emits only an explicit broadcast to this app with a bounded delay.

## Permissions and side effects

The manifest declares only the Termux RUN_COMMAND permission and package visibility for Termux. It does not declare INTERNET, microphone, camera, location, storage or foreground-service permissions. WorkManager's own manifest may merge its standard scheduling/boot permissions.

The exported wake receiver can only enqueue the fixed, constrained worker. It validates the delay, rate-limits requests and ignores requests after the user disables the cycle. The worker does not access the network. Termux executes one bounded, checkpointable local task per invocation.

Stopping cancels future periodic and one-shot work. A Termux process already started may finish its current bounded invocation and checkpoint; it is not force-killed.

## Validation boundary

The Gradle build and unit tests validate source compatibility and local scheduling policy only. They do not prove that Termux accepts RUN_COMMAND on a particular installation, that the Realme firmware honors WorkManager promptly, or that Shizuku/rish observations are available. Those require a later, explicit device validation stage.
