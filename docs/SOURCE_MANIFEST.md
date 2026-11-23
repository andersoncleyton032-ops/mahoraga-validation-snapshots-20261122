# Source and provenance manifest

## Source snapshots
- Private source repository: `andersoncleyton032-ops/mahoraga-core`
- Integrated architecture source commit: `7ed5cd893753f069ab8b33849e2bc98c22734132`
- Earlier source `main` snapshot: `498fea2c52c374c8bb661d8ead42a5bf5c55be16`
- Original source PR #142 head: `e895fadb89865a14be9a61115f9af243eb58d250`
- Original source PR #143 head: `520a3cae969845dc382b3031a10a8a71072bd322`
- Validated experimental snapshot PR #2 head at import: `e5d4ab21548df65fb589c5c645276c4dfaa3a1bd`

## Current integrated-core slice
Selected modules copied from the integrated architecture snapshot include:
- composition and coordination: `integration_core.py`, `cognitive_fabric.py`, `cognitive_engine.py`, `executive_engine.py`;
- canonical state and governance: `store.py`, `memory.py`, `autonomy_governor.py`, `dharma.py`;
- cognition and learning: `knowledge_engine.py`, `reasoning_engine.py`, `mathematics_engine.py`, `adaptive_learning.py`, `prototype_plasticity.py`, `metacognition.py`, `memory_graph.py`, `conversation_engine.py`;
- self-model, perception and capabilities: `identity_engine.py`, `introspection.py`, `hardware_intelligence.py`, `perception_engine.py`, `capability_manifest.py`, `capability_adapters.py`, `research_orchestrator.py`, `tool_intelligence.py`;
- language and runtime: `language_engine.py`, `linguistic_analysis.py`, `language_lexicon.py`, `model_runtime.py`, `command_center.py`;
- bounded supporting modules: graph algorithms, neural core/training/checkpoint preflight, CPU path tracer, image-generation orchestration, Blender bridge/intelligence client, device and diagnostic facades, telemetry and installation registry.

Selected tests cover composition, shared-store invariants, fabric signaling, governance, memory, language, neural checkpoint handling, perception, capability metadata, retrieval, resource boundaries, ledger migration, corruption detection, crash atomicity, replay, command allowlists and bounded scheduler deferral. Test fixtures are synthetic; device-specific fixture values were replaced with generic test identifiers.

## Experimental modules
The cognitive interest selector, exploration cycle, digital physiology and bounded digital-evolution VM come from the validated experimental snapshot of source PR #143. The imported snapshot contains validation fixes and is not byte-identical to the original PR. Lab-only `EvolutionGovernor`, `AutonomousLabCycle`, `PersistentAutonomousLabCycle` and `BoundedLabScheduler` were added in this public workspace; they are not private-core production modules. `agent/store.py` includes a lab-only schema-v6 append-only experiment ledger and corresponding migration.

## Lab-only adaptations and retained hardening
- `agent/actions.py` remains the checkout-scoped lab version; the current private branch's version was not copied because it defaults to `~/mahoraga`.
- `agent/physics.py` retains the lab's bounded-step and numeric-domain hardening rather than importing the older unbounded source version.
- `agent/memory.py` now uses the current shared SQLite `KnowledgeStore` API.
- CI installs NumPy for neural/vector tests and compiles all included Python sources.

## Deliberately excluded
- `memory/data.json`, `logs/activity.log`, SQLite databases and WAL/SHM files.
- Private continuity, audit, decision, session and handoff records.
- Device-specific identifiers and local hardware reports.
- Neural weights, model checkpoints, datasets, local artifacts and temporary workspaces.
- `agent/blender_python_executor.py`, `agent/blender_server_v2.py` and `agent/mahoraga_blender_addon_v2.py`; these include the high-risk execution path and are not needed for the current composition tests.
- `agent/physics.py.pre_*` historical backups.
- Original Git history and commit metadata.

This is a reviewed allowlist, not a full mirror. Future imports require file-level provenance, privacy, dependency, license, side-effect and test review.

## 2026-11-22 — persistent lifecycle, background queue and Companion candidate

### Private source lineage
- Private source repository: `andersoncleyton032-ops/mahoraga-core`.
- Integrated source ancestor: `7ed5cd893753f069ab8b33849e2bc98c22734132`.
- Stacked implementation source: `implementation/background-companion-mode-20261122`, head `87aed75ca0b24ca358c969fcae2245cf4b6a84f8`.
- Receipt-hardening source: `fix/background-execution-receipts-20261122`, head `f4fc3d8e4fd41695117f23f5f2dc490cf5137a07`.
- Private PR #157 is a draft stacked on the Companion branch; it is not merged.

### Included source and tests
- `agent/autonomy_governor.py`: foreground, screen-off idle and interactive Companion budgets.
- `agent/background_work_queue.py`: persistent queue, leases, retries, one-shot scheduler and strict completion-receipt validation.
- `agent/executive_engine.py`: three-way merge preserving the public lab's compare-and-swap focus and race-hardening additions while importing bounded internal inquiry goals.
- `agent/research_orchestrator.py`: persistent lifecycle/checkpoint integration and checkpoint sequence in the execution receipt.
- `agent/store.py`: three-way merge preserving the public lab-only schema-v6 experiment ledger while adding atomic memory/event CAS and versioned event operations.
- `experiments/persistent_digital_lifecycle.py`.
- Focused tests: autonomy governor, background queue, executive engine, persistent lifecycle, research orchestrator and Store.

### Merge and publication notes
- Public-only Store ledger code and its tests are retained; two focused CAS tests were added from the private source test suite.
- Public-only executive focus/race-hardening changes are retained; private internal-inquiry additions are merged without replacing those changes.
- Private continuity, audit and session records are not copied.
- The private `.github/workflows/physics-tests.yml` is not copied. The public repository's own `.github/workflows/snapshot-tests.yml` remains the validation workflow.
- No device identifiers, SQLite databases, WAL/SHM files, model weights, checkpoints, datasets, secrets or local workspaces are included.
- This snapshot contains Python contracts and mocked tests only. It does **not** contain an Android WorkManager Worker, a native Android app, or proof of real Android background execution.
- At initial import the candidate was pending CI; its final validation status is recorded below.

### CI correction history for the 2026-11-22 candidate
- First candidate head: `1803f91f7d9ad7fbc27410ff43df1968378f6bb4`.
- Public CI run: `45080821621`; Python 3.12 and 3.14 both compiled the source successfully, but the test step failed.
- Observed result on Python 3.12: 901 passed, 7 failed, 1 skipped and 28 subtests passed.
- Failures exposed stale test doubles missing the `work_mode` keyword, one queue fixture that discarded its Store handle, a missing `MemoryVersionConflict` test import, and event-count expectations that did not account for persisted background checkpoints.
- Corrective candidate commit: `11218303a8ec8e39db96b698f1b8fe014f090c1a`.
- The corrected candidate must receive a new CI run. The earlier failed run is retained as evidence and must not be relabeled as a pass.


### Final candidate validation — 2026-11-22
- Final validated public candidate: `6bd3a6e0d1050f857606bbef0185d171147e1b4d`.
- Workflow run #318: `45081051619`, conclusion `success`.
- Python 3.12: **908 passed, 1 skipped, 28 subtests passed**.
- Python 3.14: **908 passed, 1 skipped, 28 subtests passed**.
- Source compilation passed in both jobs.
- The single skipped test requires a local language-training corpus that is intentionally not included in the public snapshot.
- The run validates the curated Python integration only; it does not validate an Android Worker or the Realme device.

### Final Python scheduler-contract validation — 2026-11-22
- Candidate head: `b6c3b8b75061902a45b0cb6e0480cc0b7d83edb5`.
- Workflow run #321: `45081641847`, conclusion `success`.
- Python 3.12 and 3.14: **908 passed, 1 skipped, 28 subtests passed** in each environment.
- The queue now returns a structured wake request and enforces a 60-second minimum delay between chained one-shot invocations; no immediate zero-delay worker loop.

### Android WorkManager bridge validation — 2026-11-22
- Private source branch: `implementation/android-workmanager-bridge-20261122`, source head `6c87e5e8970f7e3490b559a23257ab38c4b12f40`.
- Private PR #158 remains Draft and is stacked on PR #157; no merge to `main`.
- Public validation snapshot head: `8427b4ca0b79caf4ffd60a5349b6beac0441d71b`.
- Python workflow run #335: `45084611891`, conclusion `success`; Python 3.12 and 3.14 each report **918 passed, 1 skipped, 28 subtests passed**.
- Android workflow run #13: `45084611936`, conclusion `success`; `compileDebugJavaWithJavac`, `testDebugUnitTest` and `assembleDebug` completed with **BUILD SUCCESSFUL**.
- Debug APK artifact: `mahoraga-android-bridge-debug`, artifact ID `14778647064`, approximately 2.87 MB, retained until 2026-12-06. It is a debug-only bridge package, not a production release or complete Termux distribution.
- The WorkManager Worker now independently rejects missing/invalid wake receipts and only accepts `completed` when the Python completion receipt is valid, the task ID is present and execution was actually performed. Recovered completion requires a valid durable reconciliation receipt.
- Resource policy: charging is optional; 2 GiB RAM/storage are preferred headroom, not absolute gates; 512 MiB are emergency floors. Mild thermal status keeps the bounded Companion budget; moderate reduces it, unknown permits only a minimal budget, severe/critical pauses.
- WorkManager serializes Worker execution with a single-thread executor. Its scheduler limit is left at the supported default; the queue still processes one task per invocation.
- The bridge uses Termux RUN_COMMAND >= 0.109, a result PendingIntent and a fixed Python entry point. Manual prerequisites remain: grant `com.termux.permission.RUN_COMMAND` to the bridge app and set `allow-external-apps=true` in Termux.
- Official Termux contract: https://github.com/termux/termux-app/wiki/RUN_COMMAND-Intent
- Android 12+ foreground-service background-start restrictions remain a runtime risk because Termux RUN_COMMAND promotes its service to foreground. Official Android guidance: https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start
- Private CI run #1597 (`45084587897`) failed before job steps/logs were available; it is not evidence of a Python test failure. The public isolated validation is the current executable evidence.
- CI validates Python integration and Android compilation/unit tests only. It does **not** validate Termux IPC from a background WorkManager invocation, OEM scheduling, Doze behavior or the Realme 14 5G.
- No device installation, permission grant, Termux property change, battery-setting change, Android system modification or network access has been performed.


### Worker lease fencing hardening — 2026-11-22
- Private source repository: `andersoncleyton032-ops/mahoraga-core`.
- Private source branch: `hardening/worker-fencing-and-recovery-20261123`.
- Private source branch head after the accompanying architecture specification: `065f933bcc0d81578afe66724a87d5cd6ec4c23d`; code/test change commit: `54f03366744d74b809409818b38459a848a89118`.
- Source lineage: based on `implementation/android-workmanager-bridge-20261122`, head `6c87e5e8970f7e3490b559a23257ab38c4b12f40`; no merge was performed.
- Included changes: `scripts/mahoraga_background_worker.py` now creates a unique namespaced worker identity per invocation instead of reusing the constant `android-workmanager`; `tests/test_android_workmanager_wake.py` verifies uniqueness and bounded identifier length.
- Rationale: queue ownership is fenced by `worker_id`. Reusing one identity across invocations could allow an older process to appear as the current owner after lease reclamation. Unique identities prevent stale invocations from completing/releasing a lease claimed by a later invocation.
- Public snapshot copies exactly match the private source blobs for both changed files.
- Python workflow run #337 (`45086922248`): Python 3.12 and 3.14 source compilation and all included tests passed. Android workflow run #15 (`45086922251`): Java compilation, Android unit tests and debug APK assembly passed. Artifact `mahoraga-android-bridge-debug`, ID `14779319499`, 2,872,480 bytes, SHA-256 `a1f000d220a05947cb881b7b4f0b347a6f732dea1abd80f1ea877f9893018954`, expires 2026-12-07.
- This change is not yet proven to prevent duplicate side effects from a process that continues running after the Android-side timeout; process cancellation and lease-duration alignment remain open.
- No Android app, Termux settings, permissions, device data or private repository history were changed or published.


### Android background service launch correction — 2026-11-22
- Private source branch: `hardening/worker-fencing-and-recovery-20261123`, current source head at import: `e7f158a0ef24c7a4f62f45a8e2814ba4ea7271cc`.
- Updated `TermuxBridge.java` to call `Context.startForegroundService()` on Android API 26+ and retain `startService()` only below API 26.
- Added `TermuxBridgePolicyTest` for the API 25/26 boundary and Android 12/API 31 and Android 16/API 36.
- Source rationale: Android background execution limits require a background caller targeting API 26+ to use the foreground-service launch API for a foreground service. The Android 12 foreground-service background-start restriction for cross-app starts applies only when both the caller and service-owning app target API 31+. Current upstream Termux source reports version 0.118.0 and targetSdkVersion 28, so that specific Android 12 restriction does not apply to the Termux-owned service. The Android 8+ background service API contract remains relevant to Mahoraga's targetSdk 36 caller.
- References: Android background execution limits and cross-app FGS restriction documentation; Termux upstream `app/build.gradle`, `gradle.properties`, and `RunCommandService.java`.
- Android workflow run #19 (`45087405165`) passed Java compilation, Android unit tests and debug APK assembly. Artifact ID `14780165940`, 2,872,608 bytes, SHA-256 `de11d73e02389a359041ffd08b8b63907ee68f9e17989626cf4da7ab495e3a87`, expires 2026-12-07. Even with the correct API dispatch, Realme/OEM behavior, Termux configuration and the actual background WorkManager path still require device validation.
- This change does not alter Termux settings, grant permissions, install apps or modify the device.


### Bounded Termux process and lease recovery — 2026-11-22
- Private source branch: `hardening/worker-fencing-and-recovery-20261123`, source head at import: `b66709804e5609ddcae37752e46ddabf6bf8ec7f`.
- `TermuxBridge` now invokes the Termux coreutils `timeout` utility as the fixed executable, with a 30-second process deadline, SIGTERM and a 2-second SIGKILL grace period. It fails closed if the utility is absent or not executable.
- The Android result wait remains 45 seconds, leaving time for the bounded Termux command to terminate and deliver its result.
- WorkManager retry backoff is now 120 seconds, exceeding the Python queue's 90-second default lease. This prevents the normal retry from running before an interrupted worker's lease expires and being treated as idle.
- Added Android unit tests for the timeout argument contract and for retry-backoff/lease ordering.
- This improves process lifetime and lease recovery but does not prove OS-level sandboxing. A task may still be interrupted before checkpoint; SQLite transaction recovery, idempotency and lease reconciliation remain required.
- The Termux coreutils package is marked essential upstream; the bridge nevertheless checks the exact executable at runtime rather than assuming it exists.
- Android workflow run #23 (`45087545399`) passed Java compilation, Android unit tests and debug APK assembly. Artifact ID `14779589327`, 2,872,955 bytes, SHA-256 `6c8d10f951f32d8bf7fdc13e48a2f2f814da0c7c3acf82a7a1979c890e1d0a81`, expires 2026-12-07. Device-level process termination, actual installed coreutils version and callback behavior remain untested on the Realme.


### Wake receiver sender authentication — 2026-11-22
- Private source branch: `hardening/worker-fencing-and-recovery-20261123`, updated source head at UID-authentication import: `fa46006d2825df723085338d942c5f0979567e02`.
- On Android API 34+, the exported wake receiver now accepts requests only when `BroadcastReceiver.getSentFromPackage()` identifies `com.termux`. The API call is guarded by the API 34 level check; older Android versions retain the existing explicit-action and rate-limit compatibility path.
- Added tests for matching Termux UID, mismatched UID, invalid sender UID and compatibility below API 34.
- Rationale: the receiver must remain exported for the Termux process to request a wake, but an arbitrary installed app should not be able to trigger repeated background work.
- Android workflow run #28 (`45087768537`) passed Java compilation, Android unit tests and debug APK assembly; Python run #350 (`45087768540`) passed Python 3.12/3.14 compilation and included tests. Artifact ID `14779688763`, 2,873,320 bytes, SHA-256 `b916124fff0fc9303ee48e265326790c872dd27b81ec777f45c0313dbb88afdc`, expires 2026-12-07. The sender identity returned for a real `/system/bin/am broadcast` launched from Termux must still be confirmed on the Realme before claiming the inter-app wake path works.


### Termux result-bundle truncation validation — 2026-11-22
- Private source branch: `hardening/worker-fencing-and-recovery-20261123`, source head at import: `69e35dd873aaed2b154f708aa8c13713dee3bd3a`.
- The bridge now reads Termux `stdout_original_length` and `stderr_original_length` metadata, not only the returned string sizes. Malformed or negative length metadata fails closed.
- It rejects output exceeding 48 KiB stdout, 16 KiB stderr, or 64 KiB combined, preventing acceptance of truncated JSON receipts.
- Added unit tests for valid boundaries, oversized streams, combined overflow, malformed metadata and negative lengths.
- Termux's RUN_COMMAND documentation defines these original-length fields specifically to detect truncation; the previous bridge had a parser helper but did not use it.
- Android workflow run #28 (`45087768537`) and Python workflow run #350 (`45087768540`) passed, including the exact result-bundle validation update.


### Companion execution observability — 2026-11-22
- Private source branch: `hardening/worker-fencing-and-recovery-20261123`, source head at import: `866059a5509f2cab0c7b0476322395323452db4b`.
- The Bridge Activity now queries WorkManager's unique one-shot and periodic work records and displays state, attempt count, worker status, task ID, wake status, error code and completion-receipt validity when present.
- Status can be refreshed manually and is refreshed when the Activity resumes. This is WorkManager-side observability only; it does not yet query the Termux SQLite queue directly or provide a notification channel.
- No additional Android permissions or network access are introduced.
- Validation status: **pending Android CI for this exact UI update**; device usability and display layout remain untested.


### Runtime contract documentation reconciliation — 2026-11-22
- Private source branch head at import: `f6548c4dce76ee7a23c7e486d7a8dc94c223329b`.
- Corrected stale README claims: WorkManager does not impose charging/battery/storage hard constraints; Python Governor performs admission. The Termux command is bounded by coreutils timeout; stopping future WorkManager requests does not synchronously terminate a running command.
- Documented Android API 26+ `startForegroundService()`, cross-app target SDK nuance, Android 14+ sender UID verification, output truncation checks, retry/lease relationship, APK/worker separation, and the non-sandbox nature of Termux.
- No runtime code changed in this documentation commit. Validation is through the Android CI build for the source snapshot; device behavior remains unverified.


### Cross-app foreground-service future-compatibility gate — 2026-11-22
- Private source branch: `hardening/worker-fencing-and-recovery-20261123`, source head at import: `dab6a23bc78cab907d5a0ad47ec13d49677f3fed`.
- Before RUN_COMMAND, the bridge compares Android API level, Mahoraga caller target SDK and installed Termux target SDK. If API >=31 and both apps target >=31, it fails closed with `termux_target_sdk_requires_background_fgs_review`.
- Current upstream Termux target SDK 28 does not activate the gate; the check prevents silently assuming the same exception after a future Termux target SDK increase.
- Added tests for Android API/target SDK combinations and documented the compatibility gate in the Android README.
- Validation status: **pending CI for this exact target-SDK gate**.


### Queue snapshot surfaced to WorkManager and Bridge UI — 2026-11-22
- Private source branch head at import: `d6bf02226e309937c3c654f1f56fd99756f0753f`.
- `MahoragaOneShotWorker` now preserves the Python queue summary in WorkManager output: revision, queued, claimed, active_items, recently_finished and pending.
- Bridge Activity displays the last WorkManager-reported queue counts and revision alongside task status and receipt validity.
- Added unit tests for queue snapshot propagation and for not inventing values when a queue object is absent.
- This is still a snapshot carried by the last WorkManager output; it is not a live query of SQLite. CI for this exact update is pending.
