from agent.store import KnowledgeStore
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


def candidate(candidate_id="candidate-001", risk="moderate"):
    return {
        "interest": {
            "candidate_id": candidate_id,
            "topic": "evaluate a bounded learning hypothesis",
            "relevance": 0.9, "novelty": 0.4, "uncertainty": 0.7,
            "controllability": 0.9, "learning_progress": 0.8,
            "expected_transfer": 0.8, "noise_risk": 0.1,
            "estimated_runtime_ms": 100, "estimated_ram_mb": 16,
        },
        "governance": {
            "parent_digest": "a" * 64,
            "change_scope": "experiments/candidate.py",
            "risk_class": risk,
            "estimated_test_evaluations": 100,
            "external_effects": False,
            "protected_target": False,
        },
    }


def run(lab, backlog, cycle_id="cycle-001"):
    return lab.run_cycle(
        cycle_id=cycle_id,
        state=DigitalPhysiologyState(),
        observation=observation(),
        backlog=backlog,
        base_budget=InterestBudget(1000, 128),
    )


def test_persistent_cycle_records_admission_and_reloads_after_restart(tmp_path):
    store = KnowledgeStore(tmp_path / "persistent-cycle.sqlite3")
    lab = PersistentAutonomousLabCycle(store)
    result = run(lab, [candidate()])

    assert result["admitted_candidate_ids"] == ["candidate-001"]
    assert result["experiment_records_persisted"] is True
    record_info = result["experiment_ledger"]["records"][0]
    assert record_info["decision"] == "admitted"
    assert record_info["stage"] == "triaged"

    reopened = KnowledgeStore(store.db_path)
    record = reopened.get_lab_experiment(record_info["experiment_id"])
    assert record["stage"] == "triaged"
    assert record["payload"]["candidate_id"] == "candidate-001"
    assert record["payload"]["cycle_id"] == "cycle-001"
    assert reopened.audit_lab_experiments()["invalid"] == []


def test_persistent_cycle_replay_is_idempotent_for_same_cycle(tmp_path):
    store = KnowledgeStore(tmp_path / "cycle-replay.sqlite3")
    lab = PersistentAutonomousLabCycle(store)
    backlog = [candidate()]
    first = run(lab, backlog)
    second = run(lab, backlog)

    assert first["experiment_ledger"]["created"] == 1
    assert second["experiment_ledger"]["created"] == 0
    assert second["experiment_ledger"]["replayed"] == 1
    assert second["experiment_ledger"]["records"][0]["stage"] == "triaged"
    assert len(store.list_lab_experiments()) == 1
    assert len(store.get_lab_experiment_history(
        second["experiment_ledger"]["records"][0]["experiment_id"]
    )) == 2


def test_persistent_cycle_records_policy_block_without_admitting_it(tmp_path):
    store = KnowledgeStore(tmp_path / "cycle-blocked.sqlite3")
    result = run(
        PersistentAutonomousLabCycle(store),
        [candidate(risk="critical")],
    )
    record_info = result["experiment_ledger"]["records"][0]
    record = store.get_lab_experiment(record_info["experiment_id"])

    assert result["admitted_candidate_ids"] == []
    assert record_info["decision"] == "blocked"
    assert record["stage"] == "proposed"
    assert record["payload"]["decision"]["reason"] == "high_risk_requires_separate_review"


def test_persistent_cycle_refuses_reuse_of_cycle_id_with_changed_candidate(tmp_path):
    store = KnowledgeStore(tmp_path / "cycle-conflict.sqlite3")
    lab = PersistentAutonomousLabCycle(store)
    run(lab, [candidate()])
    changed = candidate()
    changed["interest"]["topic"] = "a different hypothesis"

    try:
        run(lab, [changed])
    except Exception as exc:
        assert "conteúdo ou linhagem diferentes" in str(exc)
    else:
        raise AssertionError("Reusing a cycle ID with changed content must fail closed")


def test_persistent_cycle_keeps_production_and_execution_boundaries(tmp_path):
    store = KnowledgeStore(tmp_path / "cycle-boundaries.sqlite3")
    result = run(PersistentAutonomousLabCycle(store), [candidate()])

    assert result["candidate_discovery_performed"] is False
    assert result["workspace_created"] is False
    assert result["candidate_code_executed"] is False
    assert result["production_modified"] is False
    assert result["automatic_promotion"] is False
