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
- The new candidate is pending CI. Do not claim it passed until a workflow run for the exact resulting public commit has completed with visible steps and logs.
