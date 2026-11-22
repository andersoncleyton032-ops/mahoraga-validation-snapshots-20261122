# Autonomous evolution contract

## Intended research cycle
1. Observe explicit, non-sensitive metrics and reproducible test evidence.
2. Detect a measurable gap, regression or uncertainty.
3. Form a falsifiable hypothesis.
4. Prioritize relevance, expected learning, controllability, uncertainty, cost and risk.
5. Respect both simulated physiology and the existing core's real admission/governance contracts.
6. Isolate a candidate from a known-good checkpoint.
7. Generate or modify code only inside a bounded lab workspace.
8. Validate statically and with unit, adversarial, regression and replay tests.
9. Compare against a fixed baseline and account for resource costs.
10. Record provenance, lineage, evidence, failure data and rollback information.
11. Mark review-ready, reject or quarantine. Never promote automatically to production.
12. Select the next experiment from observed gaps, not novelty alone.

## Reuse existing core architecture
The current core slice already includes `IntegratedCore`, `CognitiveFabric`, `CognitiveEngine`, `ExecutiveEngine`, `KnowledgeStore`, `AutonomyGovernor` and `Dharma`. These remain the reference components.

- `EvolutionGovernor` is a lab-only state-machine experiment. Compare it against the existing `AutonomyGovernor` and `Dharma`; do not create a parallel production governor by default.
- `AutonomousLabCycle` is a one-step planning/admission experiment. Compare it with the existing cognitive composition and executive scheduling before proposing a new coordinator.
- Persistent experiment records should reuse the canonical `KnowledgeStore` if its contracts can safely represent them. Do not create a second canonical memory database.
- Cognitive capabilities should be recruited dynamically by context and objective, not exposed as manual modes or independent agents.
- The digital evolution VM evolves bounded scalar programs. It does not rewrite Mahoraga's source code.

## Durable experiment ledger

The isolated snapshot now adds schema v6 tables to the canonical SQLite `KnowledgeStore`: `lab_experiments` and append-only `lab_experiment_events`. Creation and lifecycle transitions commit atomically; transitions use expected-version/state checks; payloads and event envelopes have SHA-256 checksums; payloads are bounded by depth, node count and byte limits. The supported lifecycle ends at `review_ready`, `rejected` or `quarantined`. There is no promotion state or executor in this ledger.

On restart, records can be reloaded and the audit routine checks checksums, contiguous sequence numbers, version progression and allowed stage transitions. Checksums detect accidental or unsophisticated corruption; they are not cryptographic signatures against an attacker able to rewrite both data and hashes. Corrupt records fail closed and are reported; automatic repair is intentionally absent.

## Bounded batch scheduler

`BoundedLabScheduler` can process a finite caller-supplied batch of planning rounds. It validates unique cycle IDs, enforces maximum round count, cumulative declared runtime, peak declared memory and declared test-evaluation budgets, and defers remaining rounds when supplied CPU, memory, thermal or energy-drain observations exceed policy thresholds. Each accepted round uses `PersistentAutonomousLabCycle` and the canonical ledger.

The scheduler accounts only for caller-declared estimates and caller-supplied normalized observations. It does not measure real resource use, read Android sensors, sleep between rounds, start a daemon, execute candidate code or run tests. It is a bounded batch planner, not a resident continuous scheduler.

## Current boundary
The base lab coordinator consumes a caller-supplied backlog for one planning/admission cycle. `PersistentAutonomousLabCycle` wraps that coordinator and persists one cycle's candidate decisions in the canonical store, using deterministic cycle-scoped IDs and idempotent replay. The coordinator itself does not persist state. The wrapper does not discover candidates, generate patches, create workspaces, execute tests or run as a background service. The lab governor remains per-cycle/in-memory; the ledger does not authenticate external CI evidence or verify artifacts.

The integrated core modules in this snapshot are source code under test, not evidence that the full private runtime has been validated on Android or that all capabilities are enabled. The capability manifest entries remain disabled; the local model runtime remains disabled and remote access is disallowed.

## Required before unattended evolution
- A resident Android scheduler with authenticated sensor inputs, duty-cycle/pause enforcement, battery/thermal/RAM/storage monitoring and process-lifecycle recovery.
- Scheduler with explicit duty cycle, battery, thermal, memory and storage budgets.
- Candidate discovery and hypothesis generation from reproducible evidence.
- Isolated patch generation and execution with resource limits, rollback and no permission escalation.
- Independent regression/adversarial validation before review.
- Human review and approval for any production promotion.

This contract describes controlled iterative improvement. It does not assert consciousness, self-originating life, general intelligence or autonomous production deployment.
