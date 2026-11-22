# Mahoraga Experimental Lab Charter

## Purpose
An isolated, progressively expanded laboratory for testing candidate capabilities intended for Mahoraga. This is not the production core or a complete copy of every source branch.

## Separation
- The private source repository remains the protected reference.
- This public lab contains curated source snapshots, tests, provenance and experimental adaptations.
- User memory records, activity logs, device identifiers, credentials, local databases and private operational reports are excluded.
- Default persistent paths in this snapshot are rooted in this checkout, not the user's home directory.

## Experiment classes
1. Deterministic software experiments: unit/property tests, fuzzing, mutation testing and numerical stress.
2. Simulated autonomy: planning, memory policies, curiosity, goal selection, self-evaluation, resource scheduling and recovery.
3. Adversarial experiments: malformed inputs, resource exhaustion, interrupted cycles, corrupted state, dependency cycles, stale evidence and hostile filesystem layouts.
4. Hardware simulations: mocked Android, battery, thermal, memory, storage and process observations.
5. Evolution experiments: candidate generation/evaluation in closed sandboxes. The governance layer never executes candidate code or promotes it.

## Lifecycle
`PROPOSED -> TRIAGED -> SANDBOXED -> TESTED -> REVIEW_READY`
Candidates may instead become `REJECTED` or `QUARANTINED`. There is no automatic `PROMOTED` state.

## Autonomous work allowed
The system may identify reproducible gaps, form bounded hypotheses, create isolated candidates, run tests under quotas, compare against baselines, retain evidence and recommend the next experiment.

It may not modify the private source repository, merge/deploy candidates, access personal files or credentials, use external accounts/network, install packages, change Android permissions, disable safety controls, erase backups or expand its authority.

## Evidence
Every result distinguishes proposed, implemented, tested, independently reviewed and integrated. `REVIEW_READY` requires passing tests and an independent review reference. Promotion remains a separate human-controlled process.

## Resource policy
Every experiment declares runtime, memory, candidate-count and evaluation budgets. Exceeding a budget causes deferral or quarantine, never silent expansion. CI results are not claims about Android performance.

## Failure handling
Preserve the last known-good baseline. Record input, expected/actual behavior, environment, candidate digest, test evidence and rollback reference. Never overwrite the reference baseline to make a test pass.
