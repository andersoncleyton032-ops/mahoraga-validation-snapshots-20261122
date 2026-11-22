from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore
from experiments.cognitive_exploration_cycle import CognitiveExplorationCycle
from experiments.cognitive_interest_selector import InterestBudget
from experiments.digital_physiology import DigitalPhysiologyState, ResourceObservation


class ResourceFixture:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }

    def runtime_context(self, thermal_status="normal"):
        return {
            "app_foreground": True,
            "screen_interactive": True,
            "thermal_status": thermal_status,
            "source": "synthetic_test_fixture",
        }

    def resource_snapshot(self, thermal_status="normal"):
        return {
            "battery": {"termux_api": {"data": {"percentage": 90, "status": "charging"}}},
            "memory": {"values": {"MemAvailable": {"mb": 4096}}},
            "storage": {"project": {"free_bytes": 8 * 1024 * 1024 * 1024}},
            "thermal": {"status": thermal_status},
        }


def candidate(candidate_id="candidate-001"):
    return {
        "candidate_id": candidate_id,
        "topic": "validate bounded cognitive improvement",
        "relevance": 0.9,
        "novelty": 0.5,
        "uncertainty": 0.7,
        "controllability": 0.95,
        "learning_progress": 0.8,
        "expected_transfer": 0.7,
        "noise_risk": 0.1,
        "estimated_runtime_ms": 100,
        "estimated_ram_mb": 8,
    }


def observation(**overrides):
    values = {
        "cpu_load": 0.2,
        "memory_pressure": 0.2,
        "thermal_pressure": 0.1,
        "energy_drain": 0.1,
        "cooling": 0.4,
        "recharge": 0.1,
        "task_load": 0.2,
        "unresolved_uncertainty": 0.7,
        "expected_learning_progress": 0.8,
        "noise_risk": 0.1,
        "source": "synthetic_test_fixture",
    }
    values.update(overrides)
    return ResourceObservation(**values)


def make_core(tmp_path, hardware=None):
    return IntegratedCore(
        root=tmp_path,
        store=KnowledgeStore(tmp_path / "core.sqlite3"),
        hardware=hardware or ResourceFixture(),
    )


def test_interest_plan_is_admitted_only_through_real_core_governor(tmp_path):
    hardware = ResourceFixture()
    core = make_core(tmp_path, hardware)
    plan = CognitiveExplorationCycle().plan(
        state=DigitalPhysiologyState(),
        observation=observation(),
        candidates=[candidate()],
        base_budget=InterestBudget(1000, 128),
    )
    assert plan["status"] == "planned"
    candidate_id = plan["selection"]["selected_order"][0]

    session = core.autonomy.evaluate_session(
        runtime_context=hardware.runtime_context(),
        resource_snapshot=hardware.resource_snapshot(),
    )
    decision = core.autonomy.evaluate_work(
        session,
        {
            "task_id": candidate_id,
            "risk": "local_compute",
            "estimated_seconds": 1,
            "estimated_ram_mb": 16,
        },
    )

    assert decision["allowed"] is True
    assert decision["permit"]["execution_performed"] is False
    event_id = core.store.record_event(
        "experiment.admission_decided",
        {
            "candidate_id": candidate_id,
            "decision": "admitted_for_review",
            "execution_performed": False,
        },
        severity="info",
    )
    assert core.store.get_event(event_id)["event_type"] == "experiment.admission_decided"
    assert core.store.integrity_check() == "ok"


def test_hardware_thermal_pause_overrides_positive_exploration_plan(tmp_path):
    hardware = ResourceFixture()
    core = make_core(tmp_path, hardware)
    plan = CognitiveExplorationCycle().plan(
        state=DigitalPhysiologyState(),
        observation=observation(),
        candidates=[candidate()],
        base_budget=InterestBudget(1000, 128),
    )
    assert plan["selection"]["selected_order"]

    session = core.autonomy.evaluate_session(
        runtime_context=hardware.runtime_context(thermal_status="critical"),
        resource_snapshot=hardware.resource_snapshot(thermal_status="critical"),
    )
    decision = core.autonomy.evaluate_work(
        session,
        {
            "task_id": plan["selection"]["selected_order"][0],
            "risk": "local_compute",
            "estimated_seconds": 1,
            "estimated_ram_mb": 16,
        },
    )

    assert session["status"] != "bounded"
    assert decision["allowed"] is False
    assert decision["permit"]["execution_performed"] is False


def test_exploration_plan_cannot_authorize_network_or_external_effects(tmp_path):
    hardware = ResourceFixture()
    core = make_core(tmp_path, hardware)
    session = core.autonomy.evaluate_session(
        runtime_context=hardware.runtime_context(),
        resource_snapshot=hardware.resource_snapshot(),
    )

    decision = core.autonomy.evaluate_work(
        session,
        {
            "task_id": "external-candidate",
            "risk": "local_compute",
            "estimated_seconds": 1,
            "estimated_ram_mb": 16,
            "requires_network": True,
            "external_effects": True,
        },
    )

    assert decision["allowed"] is False
    assert decision["permit"]["execution_performed"] is False
