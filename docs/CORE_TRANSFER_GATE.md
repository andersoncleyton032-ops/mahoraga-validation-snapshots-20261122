# Gate for transferring validated work to private Mahoraga Core

## Source lineage — do not conflate these refs

- Private repository: `andersoncleyton032-ops/mahoraga-core`.
- Private `main` at the time of this review: `498fea2c52c374c8bb661d8ead42a5bf5c55be16`.
- Integrated architecture branch: `research/integrated-system-audit-20261122` at `7ed5cd893753f069ab8b33849e2bc98c22734132`.
- Private PR #142: head `e895fadb89865a14be9a61115f9af243eb58d250`, based on the integrated architecture branch.
- Private PR #143: head `520a3cae969845dc382b3031a10a8a71072bd322`, stacked on PR #142.
- At review time, GitHub's compare endpoint reported the integrated architecture branch and private `main` as diverged: 1,072 commits ahead, 4 behind, with 220 changed files. This is not a simple fast-forward relationship.

The public validation snapshot was curated from the integrated architecture branch, not from private `main`. Do not merge the entire integrated branch into `main`, and do not infer that a passing snapshot validates all 1,072 commits or every file in that branch.

## What has evidence in this snapshot

The current public branch `snapshot/current-core-integration-20261122` passed its included tests on Python 3.12 and 3.14 at head `c8b5233cc4b1034fd0ee76432c0b2d975b535ed1`: 846 passed, 1 skipped and 28 subtests passed on each version. The workflow uses Node 24-compatible Actions, pins pytest 9.2.0 / NumPy 2.5.5, and validates feature branches through PR events only. Run: `45042493777`.

These results validate only the included source slice and fixtures. They do not establish behavior on Android/Termux/Realme or validate the full private branch.

## Transfer classification

### Candidates for a later, narrow private-core patch

1. **Read-only diagnostic command allowlists** in `hardware_intelligence.py` and `deep_diagnostics.py`. Review against the exact target branch before porting; retain fixed command arguments, bounded output/timeouts and no shell interpolation.
2. **Executive concurrency fixes**. The optional expected-latest-event check in `KnowledgeStore.record_event_once`, the explicit focus revision in `ExecutiveEngine.set_focus`, and the post-review adoption recheck close reproducible cross-process races. These are being staged in private Draft PR #145, stacked on PR #144; private CI is still unresolved.
3. **KnowledgeStore schema-v6 ledger design**. Review migration compatibility against the exact target database schema first. The public implementation is a lab extension; do not apply it blindly to a private branch that may already have different migrations.
4. **Ledger regression tests** for migration, transaction rollback, concurrency, corruption detection and replay. Port only tests that describe the actual target-branch contract.

### Keep lab-only until a separate architecture review

- `PersistentAutonomousLabCycle`, `AutonomousLabCycle` and `EvolutionGovernor`.
- Simulated digital physiology, interest selection and the bounded digital-evolution VM.
- Any future candidate-generation or execution framework.

These are experiments, not production replacements for the existing `AutonomyGovernor`, `Dharma`, `CognitiveFabric`, `ExecutiveEngine` or canonical `KnowledgeStore`.

### Never port merely to make tests green

- Test-only expectation changes that do not correspond to a demonstrated source defect.
- Fixture-specific adapters or mocks.
- Public-lab path changes that exist only to keep writes inside this checkout.

## Required transfer procedure

1. Select the exact private target ref: integrated architecture branch, PR #142 head, PR #143 head or `main`. Never assume they are interchangeable.
2. Fetch and compare that target's current source and schema against this snapshot.
3. Create a new isolated private working branch from the chosen target ref.
4. Apply one minimal change at a time with a source-to-snapshot provenance note.
5. Preserve existing APIs, migrations and data. Add forward-only migration tests and rollback/recovery tests where applicable.
6. Run the full test suite on the private branch and inspect the exact CI head SHA.
7. Keep PR #142 and #143 open and Draft until their own review criteria are met. Do not merge or retarget them as a side effect of this work.
8. Promote only after independent review and explicit validation of the target branch.

## Current recommendation

Do not merge the public snapshot or the integrated architecture branch into private `main`. The narrow diagnostics and executive-concurrency changes are staged as Draft private PRs #144 and #145, not merged. The ledger remains lab-only until a separate schema review. Private CI is not yet conclusive because hosted jobs are failing before steps. Continue validating in this public lab; promote only the smallest independently reviewed patches once private CI can execute.
