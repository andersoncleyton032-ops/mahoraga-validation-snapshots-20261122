import pytest

from experiments.cognitive_exploration_cycle import (
    CognitiveExplorationCycle,
    CognitiveExplorationCycleError,
)
from experiments.cognitive_interest_selector import InterestBudget
from experiments.digital_physiology import (
    DigitalPhysiologyState,
    ResourceObservation,
)


def sample_observation(**overrides):
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
        "source": "simulated",
    }
    values.update(overrides)
    return ResourceObservation(**values)


def sample_candidate(candidate_id="topic", **overrides):
    values = {
        "candidate_id": candidate_id,
        "topic": "investigar uma questão ainda não resolvida",
        "relevance": 0.8,
        "novelty": 0.5,
        "uncertainty": 0.7,
        "controllability": 0.9,
        "learning_progress": 0.6,
        "expected_transfer": 0.8,
        "noise_risk": 0.1,
        "estimated_runtime_ms": 100,
        "estimated_ram_mb": 16,
        "dependencies": [],
        "evidence_refs": [],
    }
    values.update(overrides)
    return values


def test_healthy_state_allows_interest_selection_with_shared_budget():
    cycle = CognitiveExplorationCycle()
    result = cycle.plan(
        state=DigitalPhysiologyState(),
        observation=sample_observation(),
        candidates=[sample_candidate()],
        base_budget=InterestBudget(1000, 128, max_selected=8),
    )

    assert result["status"] == "planned"
    assert result["selection"]["selected_roots"] == ["topic"]
    assert result["selection"]["budget"]["max_runtime_ms"] < 1000
    assert result["selection"]["budget"]["max_ram_mb"] < 128
    assert result["physiology"]["state"]["control_state"] == "normal"
    assert result["candidate_discovery_performed"] is False
    assert result["goal_created"] is False
    assert result["work_executed"] is False
    assert result["authorization_granted"] is False


def test_critical_homeostatic_pause_defers_before_selector_is_called():
    class NeverCallSelector:
        def select(self, *args, **kwargs):
            raise AssertionError("selector must not run during a critical pause")

    cycle = CognitiveExplorationCycle(selector=NeverCallSelector())
    state = DigitalPhysiologyState(
        energy_reserve=0.2,
        thermal_load=0.96,
        memory_pressure=0.2,
        cognitive_load=0.2,
        control_state="normal",
    )
    result = cycle.plan(
        state=state,
        observation=sample_observation(
            cpu_load=1.0, thermal_pressure=1.0,
            energy_drain=1.0, cooling=0.0, task_load=1.0,
        ),
        candidates=[sample_candidate()],
        base_budget=InterestBudget(1000, 128),
    )

    assert result["status"] == "deferred"
    assert result["reason"] == "homeostatic_pause"
    assert result["selection"] is None
    assert result["memory_persisted"] is False
    assert result["goal_created"] is False
    assert result["work_executed"] is False


def test_strained_state_raises_utility_bar_and_abstains_on_low_value_candidate():
    cycle = CognitiveExplorationCycle()
    candidate = sample_candidate(
        relevance=0.2,
        novelty=0.2,
        uncertainty=0.2,
        controllability=0.5,
        learning_progress=0.2,
        expected_transfer=0.2,
        noise_risk=0.1,
    )
    healthy = cycle.plan(
        state=DigitalPhysiologyState(),
        observation=sample_observation(unresolved_uncertainty=1.0, expected_learning_progress=1.0, noise_risk=0.0),
        candidates=[candidate],
        base_budget=InterestBudget(10000, 1024),
        minimum_score=0.05,
    )
    strained = cycle.plan(
        state=DigitalPhysiologyState(
            energy_reserve=0.8,
            thermal_load=0.8,
            memory_pressure=0.8,
            cognitive_load=0.8,
            recovery_reserve=0.2,
            control_state="normal",
        ),
        observation=sample_observation(
            cpu_load=0.2, thermal_pressure=0.9,
            energy_drain=0.0, cooling=0.2,
            task_load=0.2,
            unresolved_uncertainty=1.0,
            expected_learning_progress=1.0,
            noise_risk=0.0,
        ),
        candidates=[candidate],
        base_budget=InterestBudget(10000, 1024),
        minimum_score=0.05,
    )

    assert healthy["status"] == "planned"
    assert strained["status"] == "abstain"
    assert strained["reason"] == "homeostasis_adjusted_candidate_selection"
    assert strained["selection"]["budget"]["max_runtime_ms"] < healthy["selection"]["budget"]["max_runtime_ms"]


def test_zero_exploration_budget_defers_before_selector_is_called():
    class NeverCallSelector:
        def select(self, *args, **kwargs):
            raise AssertionError("selector must not run without exploration capacity")

    cycle = CognitiveExplorationCycle(selector=NeverCallSelector())
    result = cycle.plan(
        state=DigitalPhysiologyState(),
        observation=sample_observation(unresolved_uncertainty=0.0),
        candidates=[sample_candidate()],
        base_budget=InterestBudget(1000, 128),
    )
    assert result["status"] == "deferred"
    assert result["reason"] == "insufficient_admission_budget"
    assert result["effective_exploration_factor"] == 0.0
    assert result["selection"] is None


def test_exploration_budget_scales_admission_and_noise():
    cycle = CognitiveExplorationCycle()
    base = InterestBudget(1000, 128, max_selected=8)
    low_noise = cycle.plan(
        state=DigitalPhysiologyState(),
        observation=sample_observation(noise_risk=0.0),
        candidates=[sample_candidate()],
        base_budget=base,
    )
    high_noise = cycle.plan(
        state=DigitalPhysiologyState(),
        observation=sample_observation(noise_risk=0.8),
        candidates=[sample_candidate()],
        base_budget=base,
    )
    assert high_noise["effective_exploration_factor"] < low_noise["effective_exploration_factor"]
    assert high_noise["selection"]["budget"]["max_runtime_ms"] < low_noise["selection"]["budget"]["max_runtime_ms"]


def test_empty_candidate_set_abstains_without_side_effects():
    result = CognitiveExplorationCycle().plan(
        state=DigitalPhysiologyState(),
        observation=sample_observation(),
        candidates=[],
        base_budget=InterestBudget(1000, 128),
    )
    assert result["status"] == "abstain"
    assert result["selection"]["selected_order"] == []
    assert result["work_executed"] is False
    assert result["authorization_granted"] is False


@pytest.mark.parametrize("bad_minimum", [True, float("nan"), float("inf"), -0.1, 1.1, "0.5", 10**1000])
def test_invalid_minimum_score_is_rejected(bad_minimum):
    with pytest.raises(CognitiveExplorationCycleError):
        CognitiveExplorationCycle().plan(
            state=DigitalPhysiologyState(),
            observation=sample_observation(),
            candidates=[],
            base_budget=InterestBudget(1000, 128),
            minimum_score=bad_minimum,
        )


def test_invalid_context_and_candidate_schema_are_rejected():
    cycle = CognitiveExplorationCycle()
    with pytest.raises(CognitiveExplorationCycleError, match="state inválido"):
        cycle.plan(
            state={},
            observation=sample_observation(),
            candidates=[],
            base_budget=InterestBudget(1000, 128),
        )
    with pytest.raises(CognitiveExplorationCycleError, match="incompatível"):
        cycle.plan(
            state=DigitalPhysiologyState(),
            observation=sample_observation(),
            candidates=[{"candidate_id": "bad"}],
            base_budget=InterestBudget(1000, 128),
        )
