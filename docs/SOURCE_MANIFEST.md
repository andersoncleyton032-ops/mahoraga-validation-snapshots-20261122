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
