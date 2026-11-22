import pytest

from agent.store import KnowledgeStore
from experiments.bounded_lab_scheduler import (
    BoundedLabScheduler,
    LabSchedulerError,
    LabSchedulerPolicy,
)
from experiments.cognitive_interest_selector import InterestBudget
from experiments.digital_physiology import DigitalPhysiologyState, ResourceObservation
from experiments.persistent_lab_cycle import PersistentAutonomousLabCycle


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


def candidate(candidate_id):
    return {
        "interest": {
            "candidate_id": candidate_id, "topic": "bounded scheduler hypothesis",
            "relevance": 0.9, "novelty": 0.4, "uncertainty": 0.7,
            "controllability": 0.9, "learning_progress": 0.8,
            "expected_transfer": 0.8, "noise_risk": 0.1,
            "estimated_runtime_ms": 100, "estimated_ram_mb": 16,
        },
        "governance": {
            "parent_digest": "a" * 64,
            "change_scope": "experiments/scheduler_candidate.py",
            "risk_class": "moderate",
            "estimated_test_evaluations": 100,
            "external_effects": False,
            "protected_target": False,
        },
    }


def round_request(cycle_id, **overrides):
    value = {
        "cycle_id": cycle_id,
        "state": DigitalPhysiologyState(),
        "observation": observation(),
        "backlog": [candidate(f"candidate-{cycle_id}")],
        "base_budget": InterestBudget(1000, 128),
        "estimated_runtime_ms": 1000,
        "estimated_memory_mb": 32,
        "estimated_test_evaluations": 100,
    }
    value.update(overrides)
    return value


def scheduler(tmp_path, policy=None):
    store = KnowledgeStore(tmp_path / "scheduler.sqlite3")
    return BoundedLabScheduler(PersistentAutonomousLabCycle(store), policy), store


def test_scheduler_runs_bounded_planning_rounds_and_persists_each_cycle(tmp_path):
    lab, store = scheduler(tmp_path)
    result = lab.run_batch([
        round_request("round-1"),
        round_request("round-2"),
    ])

    assert result["status"] == "completed"
    assert len(result["planned_rounds"]) == 2
    assert result["deferred_rounds"] == []
    assert result["resource_accounting"]["estimated_total_runtime_ms"] == 2000
    assert result["resource_accounting"]["estimated_peak_memory_mb"] == 32
    assert len(store.list_lab_experiments()) == 2
    assert result["candidate_code_executed"] is False
    assert result["tests_executed_by_scheduler"] is False
    assert result["background_service_started"] is False
    assert result["production_modified"] is False


def test_scheduler_defers_all_rounds_when_thermal_pressure_is_high(tmp_path):
    lab, store = scheduler(tmp_path)
    result = lab.run_batch([
        round_request("hot-1", observation=observation(thermal_pressure=0.9)),
        round_request("hot-2"),
    ])

    assert result["status"] == "deferred"
    assert result["stop_reason"] == "thermal_pressure_limit"
    assert result["planned_rounds"] == []
    assert len(result["deferred_rounds"]) == 2
    assert store.list_lab_experiments() == []


def test_scheduler_enforces_cumulative_runtime_budget(tmp_path):
    policy = LabSchedulerPolicy(max_total_runtime_ms=5000)
    lab, store = scheduler(tmp_path, policy)
    result = lab.run_batch([
        round_request("budget-1", estimated_runtime_ms=4000),
        round_request("budget-2", estimated_runtime_ms=2000),
    ])

    assert result["status"] == "partially_completed"
    assert [item["cycle_id"] for item in result["planned_rounds"]] == ["budget-1"]
    assert result["deferred_rounds"][0]["cycle_id"] == "budget-2"
    assert result["stop_reason"] == "total_runtime_budget_exceeded"
    assert len(store.list_lab_experiments()) == 1


def test_scheduler_enforces_peak_memory_and_evaluation_budgets(tmp_path):
    policy = LabSchedulerPolicy(max_peak_memory_mb=64, max_total_test_evaluations=150)
    lab, store = scheduler(tmp_path, policy)
    result = lab.run_batch([
        round_request("memory-1", estimated_memory_mb=65),
    ])
    assert result["stop_reason"] == "peak_memory_budget_exceeded"
    assert store.list_lab_experiments() == []

    result = lab.run_batch([
        round_request("eval-1", estimated_test_evaluations=100),
        round_request("eval-2", estimated_test_evaluations=100),
    ])
    assert len(result["planned_rounds"]) == 1
    assert result["stop_reason"] == "test_evaluation_budget_exceeded"
    assert len(store.list_lab_experiments()) == 1


def test_scheduler_validates_round_count_ids_and_declared_estimates(tmp_path):
    policy = LabSchedulerPolicy(max_rounds=1)
    lab, _ = scheduler(tmp_path, policy)
    with pytest.raises(LabSchedulerError, match="Quantidade"):
        lab.run_batch([round_request("one"), round_request("two")])
    with pytest.raises(LabSchedulerError, match="duplicado"):
        lab.run_batch([round_request("same"), round_request("same")])
    with pytest.raises(LabSchedulerError, match="estimated_runtime_ms"):
        lab.run_batch([round_request("bad", estimated_runtime_ms=True)])


def test_scheduler_policy_rejects_unbounded_values():
    for kwargs in (
        {"max_rounds": 17},
        {"max_total_runtime_ms": 600001},
        {"max_peak_memory_mb": 4097},
        {"max_total_test_evaluations": 1_000_001},
        {"max_thermal_pressure": 1.1},
    ):
        with pytest.raises(LabSchedulerError):
            LabSchedulerPolicy(**kwargs)
