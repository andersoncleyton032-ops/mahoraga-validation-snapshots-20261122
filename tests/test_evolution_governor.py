import pytest

from experiments.evolution_governor import (
    CandidateStage, EvolutionGovernanceError, EvolutionGovernor, EvolutionPolicy,
)

PARENT = "a" * 64
CANDIDATE = "b" * 64


def register(governor, candidate_id="candidate-1", **overrides):
    values = {
        "candidate_id": candidate_id, "parent_digest": PARENT,
        "change_scope": "experiments/candidate.py", "risk_class": "moderate",
        "estimated_runtime_seconds": 60, "estimated_memory_mb": 128,
        "estimated_test_evaluations": 500,
    }
    values.update(overrides)
    return governor.register(**values)


def advance_to_sandbox(governor, candidate_id="candidate-1"):
    register(governor, candidate_id)
    governor.transition(candidate_id, CandidateStage.TRIAGED, evidence_ref="triage:001")
    return governor.transition(candidate_id, CandidateStage.SANDBOXED, evidence_ref="sandbox:001")


def test_lifecycle_requires_ordered_evidence_and_stops_at_review():
    governor = EvolutionGovernor()
    advance_to_sandbox(governor)
    with pytest.raises(EvolutionGovernanceError):
        governor.transition("candidate-1", CandidateStage.REVIEW_READY, evidence_ref="review:001")
    tested = governor.transition("candidate-1", CandidateStage.TESTED, evidence_ref="ci:run-001",
                                 tests_passed=12, tests_total=12, candidate_digest=CANDIDATE)
    assert tested.stage is CandidateStage.TESTED
    reviewed = governor.transition("candidate-1", CandidateStage.REVIEW_READY,
                                   evidence_ref="independent-review:review-001")
    assert reviewed.stage is CandidateStage.REVIEW_READY
    assert governor.snapshot()["automatic_promotion"] is False


def test_failed_or_empty_test_evidence_cannot_mark_candidate_tested():
    governor = EvolutionGovernor()
    advance_to_sandbox(governor)
    for passed, total in ((0, 0), (2, 3), (3, 2)):
        with pytest.raises(EvolutionGovernanceError):
            governor.transition("candidate-1", CandidateStage.TESTED, evidence_ref="ci:failed",
                                tests_passed=passed, tests_total=total, candidate_digest=CANDIDATE)


@pytest.mark.parametrize("flag", ["external_effects", "protected_target"])
def test_external_effects_and_protected_targets_are_rejected(flag):
    with pytest.raises(EvolutionGovernanceError):
        register(EvolutionGovernor(), **{flag: True})


def test_high_risk_candidate_cannot_be_auto_admitted():
    governor = EvolutionGovernor()
    register(governor, risk_class="high")
    with pytest.raises(EvolutionGovernanceError):
        governor.transition("candidate-1", CandidateStage.TRIAGED, evidence_ref="triage:high")


def test_resource_quotas_are_enforced_before_candidate_admission():
    governor = EvolutionGovernor(EvolutionPolicy(max_runtime_seconds=30))
    with pytest.raises(EvolutionGovernanceError):
        register(governor, estimated_runtime_seconds=31)


def test_active_candidate_capacity_is_bounded():
    governor = EvolutionGovernor(EvolutionPolicy(max_active_candidates=1))
    register(governor, "one")
    with pytest.raises(EvolutionGovernanceError):
        register(governor, "two")
    governor.transition("one", CandidateStage.REJECTED, evidence_ref="reject:one")
    register(governor, "two")


def test_review_requires_independent_review_reference():
    governor = EvolutionGovernor()
    advance_to_sandbox(governor)
    governor.transition("candidate-1", CandidateStage.TESTED, evidence_ref="ci:run",
                        tests_passed=1, tests_total=1, candidate_digest=CANDIDATE)
    with pytest.raises(EvolutionGovernanceError):
        governor.transition("candidate-1", CandidateStage.REVIEW_READY, evidence_ref="ci:run")


@pytest.mark.parametrize(
    "scope",
    [
        "agent/main.py",
        "memory/data.json",
        ".github/workflows/ci.yml",
        "../agent/main.py",
        "experiments/../../agent/main.py",
        "/tmp/candidate.py",
        "experiments\\candidate.py",
    ],
)
def test_candidate_scope_cannot_escape_experimental_directories(scope):
    with pytest.raises(EvolutionGovernanceError):
        register(EvolutionGovernor(), change_scope=scope)


def test_unhashable_risk_class_is_rejected_as_domain_error():
    with pytest.raises(EvolutionGovernanceError):
        register(EvolutionGovernor(), risk_class=[])


def test_candidate_identifiers_and_digests_are_validated():
    governor = EvolutionGovernor()
    with pytest.raises(EvolutionGovernanceError):
        register(governor, candidate_id="../escape")
    with pytest.raises(EvolutionGovernanceError):
        register(governor, parent_digest="not-a-digest")


def test_snapshot_is_deterministic_and_denies_authority():
    first, second = EvolutionGovernor(), EvolutionGovernor()
    for governor in (first, second):
        register(governor)
        governor.transition("candidate-1", CandidateStage.TRIAGED, evidence_ref="triage:1")
    assert first.snapshot() == second.snapshot()
    assert first.snapshot()["automatic_execution"] is False
    assert first.snapshot()["external_effects_allowed"] is False
