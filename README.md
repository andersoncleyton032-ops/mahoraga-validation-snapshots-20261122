# Mahoraga — Experimental Validation Lab

This public repository is a **curated experimental workspace**, not a complete or automatically synchronized mirror of the private Mahoraga Core.

## Purpose
Stress-test selected ideas intended for Mahoraga: cognitive planning, simulated physiology, bounded digital evolution, adversarial validation and controlled self-improvement workflows.

## What this snapshot represents
- The small `agent/` console and utility subset was copied from private `mahoraga-core/main` at source commit `498fea2c52c374c8bb661d8ead42a5bf5c55be16`. It is a legacy/minimal baseline, **not the current integrated cognitive runtime**.
- The cognitive interest, physiology and digital evolution experiments were imported from a separately validated snapshot of source PR #143, with validation fixes documented in the source manifest.
- New lab-only governance and orchestration code is experimental. It is not a replacement for the private core's existing `AutonomyGovernor`, `Dharma`, `KnowledgeStore`, `IntegratedCore` or `CognitiveFabric`.

## Separation and publication
- The private source repository remains the protected reference.
- Personal memory, activity logs, device-specific state, credentials, private operational reports and original Git history are excluded.
- Persistent paths in this snapshot point inside this checkout, not `~/mahoraga`.
- Candidate code scope is limited to `experiments/`, `tests/` and `docs/`; this does not prevent maintainers from separately reviewing lab infrastructure.
- No candidate code is automatically executed, installed, merged or promoted into the private core.
- New imports require a file-level privacy, provenance, dependency, license and test review.

## Start here
- [Lab charter](docs/LAB_CHARTER.md)
- [Source manifest](docs/SOURCE_MANIFEST.md)
- [Autonomous evolution contract](docs/AUTONOMOUS_EVOLUTION_CONTRACT.md)

## Experimental components
- Cognitive interest selection and exploration planning.
- Simulated digital physiology and resource-aware admission.
- A closed virtual machine for bounded digital evolution.
- An evidence-gated experimental candidate lifecycle.
- A one-step lab coordinator joining planning and governance.

## Validation
CI compiles included Python sources and runs the included tests on Python 3.12 and 3.14. Passing tests demonstrate only the tested contracts in this curated snapshot. They do not validate the private integrated runtime, Android/Termux behavior, persistent unattended autonomy or general intelligence.
