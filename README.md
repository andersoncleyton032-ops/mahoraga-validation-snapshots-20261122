# Mahoraga — Curated Core Validation Lab

This public repository is a **curated, sanitized validation snapshot** of selected Mahoraga Core code and experiments. It is not a complete mirror and is not automatically synchronized with the private repository.

## What this snapshot contains
- A selected slice of the current integrated architecture: `IntegratedCore`, `CognitiveFabric`, `CognitiveEngine`, `ExecutiveEngine`, `KnowledgeStore`, `AutonomyGovernor`, `Dharma`, introspection, identity, learning, metacognition, language, perception, capability adapters and related modules.
- Selected integration, regression, resource-boundary and adversarial tests for those modules.
- Non-sensitive capability, identity, model-runtime and neural-stack configuration. All capability entries remain disabled; local model runtime remains disabled and remote access is disallowed.
- Cognitive interest selection, simulated physiology and bounded digital-evolution experiments from the validated experiment snapshot.
- Lab-only candidate-governance prototypes and a replay-safe persistent lab-cycle wrapper. The wrapper records planning/admission decisions in the canonical SQLite store but does not execute candidate code or promote changes.

## What is deliberately not copied
- Private continuity records, audit logs, work-session history or internal operational reports.
- User/project memory data, activity logs, local SQLite databases, model weights, checkpoints, datasets or device-specific identifiers.
- Original Git history and commit metadata.
- The Blender Python executor, server and add-on that can run arbitrary Python inside Blender. The client/bridge code is included for static and mocked contract testing only.
- The original `agent/actions.py` from the current private branch because its default path targets `~/mahoraga`; this lab retains a checkout-scoped version instead.
- The private repository's entire source tree, branches and PR history.

See [Source Manifest](docs/SOURCE_MANIFEST.md), [Publication Policy](docs/PUBLICATION_POLICY.md) and [Core Transfer Gate](docs/CORE_TRANSFER_GATE.md).

## Architecture boundary
The private core's existing `AutonomyGovernor`, `Dharma`, `KnowledgeStore`, `IntegratedCore` and `CognitiveFabric` remain the reference architecture. Lab-only `EvolutionGovernor`, `AutonomousLabCycle` and `PersistentAutonomousLabCycle` are experiments to compare against those components, not replacements. The persistent wrapper stores cycle-scoped candidate records in the lab's schema-v6 SQLite ledger.

## Validation
CI compiles included Python sources and runs the included tests on Python 3.12 and 3.14. Tests on this public snapshot do not prove Android/Termux/Realme behavior, continuous background execution, unattended code evolution, general intelligence or production readiness.
