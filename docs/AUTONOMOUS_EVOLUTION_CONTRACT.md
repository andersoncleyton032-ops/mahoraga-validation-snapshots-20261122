# Autonomous evolution contract

## Closed-loop research cycle
1. Observe explicitly supplied, non-sensitive metrics and test evidence.
2. Detect a reproducible gap, regression or uncertainty.
3. Form a falsifiable hypothesis.
4. Prioritize learning value, relevance, controllability, noise and resource cost.
5. Admit only within homeostatic/resource budgets; otherwise defer.
6. Isolate a candidate from a known-good checkpoint.
7. Develop a bounded patch; do not run candidate code outside the isolated runner.
8. Verify with static, unit, adversarial, regression and deterministic replay tests.
9. Evaluate against baseline and account for every execution/resource cost.
10. Record evidence, limitations, digest, lineage and failure data.
11. Mark review-ready, reject or quarantine. No automatic production promotion.
12. Select the next experiment from measured gaps, not novelty alone.

## Relationship to the private Mahoraga Core
The private core already contains architecture that this old curated snapshot does not reproduce: `IntegratedCore`, `CognitiveFabric`, `CognitiveEngine`, `ExecutiveEngine`, `KnowledgeStore`, `AutonomyGovernor`, `Dharma`, introspection, metacognition, learning, memory graph, perception and tool adapters.

Therefore:
- `EvolutionGovernor` is a lab-only state-machine experiment. It must be compared against the existing `AutonomyGovernor` and `Dharma` before any integration proposal. It must not become a parallel production governor by default.
- `AutonomousLabCycle` is a one-step planning/admission experiment. It must be compared with existing cognitive composition and executive scheduling before proposing a new runtime coordinator.
- The ledger/persistence direction must reuse and extend the existing `KnowledgeStore` if its contracts can safely represent experiment events. Do not create a second canonical memory database merely for the experiment.
- Cognitive capabilities must be recruited dynamically by context and objective, not exposed as manual modes or independent agents.

## Current implementation boundary
`AutonomousLabCycle` connects simulated physiology, interest selection and the lab-only evolution governor for **one bounded planning/admission cycle**. It consumes a caller-supplied backlog. It does not discover new candidates, generate code, create workspaces, execute tests itself, persist its state, or run as a background service.

`EvolutionGovernor` tracks an in-memory candidate lifecycle and evidence. Its snapshot is deterministic, but persistence and restart recovery are not implemented. Evidence references are supplied by the caller; the governor does not authenticate their contents. The digital evolution engine evolves bounded scalar programs inside its closed VM; it does not evolve Mahoraga's source code.

The small `agent/main.py` in this repository is a legacy/minimal console entrypoint from the curated source baseline. It is not the current integrated runtime and must not be used as proof of the full system's behavior.

## Capability boundaries
Research/planning are advisory. Candidate code changes are limited to the lab's `experiments/`, `tests/` and `docs/` paths. The governor records lifecycle/evidence; it does not execute code. The CI runner executes the repository's test suite, not generated candidate programs. No network, shell, package installation, Android permission, personal-data or production-repository capability is granted to the governor.

## Minimum review evidence
Immutable candidate ID/digest; parent checkpoint and provenance; declared scope/risk; reproducible command/environment; passing tests/logs; adversarial/resource results; limitations/rollback; independent review reference.

## Work still required for unattended evolution
- durable, corruption-detecting experiment ledger and safe restart recovery, integrated with the existing canonical store rather than a parallel memory system;
- scheduler/daemon with explicit duty cycle, battery, thermal, memory and storage budgets;
- candidate discovery and hypothesis generation from reproducible evidence;
- isolated patch generation and execution, with resource limits and rollback;
- independent regression and adversarial validation before review;
- notification and human approval workflow for production promotion.

These components must be developed and tested separately. A scheduled loop must pause safely when resources are constrained and must not expand its own permissions.

This contract does not assert consciousness, self-originating life, general intelligence or autonomous production deployment. It defines controlled iterative improvement.
