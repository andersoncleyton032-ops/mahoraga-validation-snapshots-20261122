import pytest

from experiments.autonomous_lab_cycle import AutonomousLabCycle, AutonomousLabCycleError
from experiments.cognitive_interest_selector import InterestBudget
from experiments.digital_physiology import DigitalPhysiologyState, ResourceObservation
from experiments.evolution_governor import CandidateStage


def observation(**overrides):
    values = {
        "cpu_load": 0.2, "memory_pressure": 0.2, "thermal_pressure": 0.1,
        "energy_drain": 0.1, "cooling": 0.4, "recharge": 0.1,
        "task_load": 0.2, "unresolved_uncertainty": 0.7,
        "expected_learning_progress": 0.8, "noise_risk": 0.1,
        "source": "simulated",
    }
    values.update(overrides)
    return ResourceObservation(**values)


def candidate(candidate_id="exp-001", **governance_overrides):
    interest = {
        "candidate_id": candidate_id, "topic": "test a bounded adaptation",
        "relevance": 0.9, "novelty": 0.4, "uncertainty": 0.7,
        "controllability": 0.9, "learning_progress": 0.8,
        "expected_transfer": 0.8, "noise_risk": 0.1,
        "estimated_runtime_ms": 100, "estimated_ram_mb": 16,
    }
    governance = {
        "parent_digest": "a" * 64,
        "change_scope": "experiments/candidate.py",
        "risk_class": "moderate",
        "estimated_test_evaluations": 100,
        "external_effects": False,
        "protected_target": False,
    }
    governance.update(governance_overrides)
    return {"interest": interest, "governance": governance}


def run(cycle, backlog, observation_value=None, cycle_id="cycle-001"):
    return cycle.run_cycle(
        cycle_id=cycle_id,
        state=DigitalPhysiologyState(),
        observation=observation_value or observation(),
        backlog=backlog,
        base_budget=InterestBudget(1000, 128),
    )


def test_cycle_connects_physiology_interest_and_governance_without_execution():
    cycle = AutonomousLabCycle()
    result = run(cycle, [candidate()])
    assert result["status"] == "admitted"
    assert result["admitted_candidate_ids"] == ["exp-001"]
    assert cycle.governor.get("exp-001").stage is CandidateStage.TRIAGED
    assert result["workspace_created"] is False
    assert result["candidate_code_executed"] is False
    assert result["production_modified"] is False
    assert result["automatic_promotion"] is False


def test_zero_exploration_capacity_defers_without_admitting_candidates():
    cycle = AutonomousLabCycle()
    result = run(cycle, [candidate()], observation(unresolved_uncertainty=0.0))
    assert result["status"] == "deferred"
    assert result["admitted_candidate_ids"] == []
    assert result["governor"]["candidates"] == []


def test_high_risk_candidates_are_not_auto_admitted():
    cycle = AutonomousLabCycle()
    result = run(cycle, [candidate(risk_class="high")])
    assert result["status"] == "blocked"
    assert result["blocked_candidates"][0]["reason"] == "high_risk_requires_separate_review"
    assert result["governor"]["candidates"] == []


def test_dependent_candidate_is_blocked_when_dependency_is_not_admitted():
    cycle = AutonomousLabCycle()
    dependency = candidate("dependency-001", risk_class="high")
    root = candidate("root-001")
    dependency["interest"]["estimated_runtime_ms"] = 1
    dependency["interest"]["estimated_ram_mb"] = 1
    root["interest"]["estimated_runtime_ms"] = 1
    root["interest"]["estimated_ram_mb"] = 1
    root["interest"]["dependencies"] = ["dependency-001"]
    result = run(cycle, [dependency, root])
    assert result["status"] == "blocked"
    assert result["admitted_candidate_ids"] == []
    reasons = {item["candidate_id"]: item["reason"] for item in result["blocked_candidates"]}
    assert reasons["dependency-001"] == "high_risk_requires_separate_review"
    assert reasons["root-001"] == "dependency_not_admitted:dependency-001"


def test_protected_core_paths_are_rejected_by_governance():
    cycle = AutonomousLabCycle()
    result = run(cycle, [candidate(change_scope="agent/main.py")])
    assert result["status"] == "blocked"
    assert "permitted lab directories" in result["blocked_candidates"][0]["reason"]
    assert result["governor"]["candidates"] == []


def test_high_noise_suppresses_admission_budget():
    cycle = AutonomousLabCycle()
    low = run(cycle, [candidate()], observation(noise_risk=0.0), "low-noise")
    high_cycle = AutonomousLabCycle()
    high = run(high_cycle, [candidate()], observation(noise_risk=0.95), "high-noise")
    assert high["planning"]["effective_exploration_factor"] < low["planning"]["effective_exploration_factor"]


def test_invalid_cycle_id_and_envelope_are_rejected():
    cycle = AutonomousLabCycle()
    with pytest.raises(AutonomousLabCycleError):
        run(cycle, [candidate()], cycle_id="../escape")
    with pytest.raises(AutonomousLabCycleError):
        run(AutonomousLabCycle(), [{"interest": {}, "governance": {}}])
