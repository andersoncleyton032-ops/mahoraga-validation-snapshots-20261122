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

## Capability boundaries
Research/planning are advisory. Candidate generation is confined to the lab. Candidate execution is allowed only in a bounded CI/test runner. The governor records lifecycle/evidence; it does not execute code. No network, shell, package installation, Android permission, personal-data or production-repository capability is granted here.

## Minimum review evidence
Immutable candidate ID/digest; parent checkpoint and provenance; declared scope/risk; reproducible command/environment; passing tests/logs; adversarial/resource results; limitations/rollback; independent review reference.

This contract does not assert consciousness, self-originating life, general intelligence or autonomous production deployment. It defines controlled iterative improvement.
