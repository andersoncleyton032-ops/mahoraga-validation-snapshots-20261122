import pytest

from experiments.digital_physiology import (
    DigitalHomeostasis,
    DigitalPhysiologyError,
    DigitalPhysiologyState,
    PhysiologyConfig,
    ResourceObservation,
)


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
        "source": "simulated",
    }
    values.update(overrides)
    return ResourceObservation(**values)


def test_homeostasis_updates_state_deterministically():
    regulator = DigitalHomeostasis()
    state = DigitalPhysiologyState()
    first = regulator.update(state, observation())
    second = regulator.update(state, observation())

    assert first == second
    assert first["state"]["cycle"] == 1
    assert first["state"]["energy_reserve"] < state.energy_reserve
    assert first["state"]["thermal_load"] < state.thermal_load
    assert first["state"]["control_state"] == "normal"


def test_resource_pressure_reduces_attention_and_exploration_budget():
    regulator = DigitalHomeostasis()
    state = DigitalPhysiologyState()
    healthy = regulator.update(state, observation())
    strained = regulator.update(
        DigitalPhysiologyState(
            energy_reserve=0.28,
            thermal_load=0.82,
            memory_pressure=0.90,
            cognitive_load=0.85,
            recovery_reserve=0.2,
        ),
        observation(
            cpu_load=0.95, memory_pressure=0.98, thermal_pressure=0.98,
            energy_drain=0.9, cooling=0.0, task_load=0.95,
            noise_risk=0.8,
        ),
    )

    assert strained["regulation"]["attention_budget"] < healthy["regulation"]["attention_budget"]
    assert strained["regulation"]["exploration_budget"] < healthy["regulation"]["exploration_budget"]
    assert strained["regulation"]["recommended_admission_factor"] <= 0.5


def test_critical_pressure_enters_pause_state():
    regulator = DigitalHomeostasis()
    state = DigitalPhysiologyState(thermal_load=0.96)
    result = regulator.update(
        state,
        observation(
            cpu_load=1.0, thermal_pressure=1.0,
            cooling=0.0, task_load=1.0,
        ),
    )
    assert result["state"]["control_state"] == "pause"
    assert result["regulation"]["recommended_admission_factor"] == 0.0


def test_pause_uses_hysteresis_before_recovering_and_resuming():
    regulator = DigitalHomeostasis()
    state = DigitalPhysiologyState(
        energy_reserve=0.9,
        thermal_load=0.96,
        memory_pressure=0.2,
        cognitive_load=0.2,
        control_state="pause",
    )
    still_hot = regulator.update(
        state,
        observation(
            cpu_load=0.0, thermal_pressure=0.96,
            cooling=0.5, task_load=0.0,
        ),
    )
    assert still_hot["state"]["control_state"] == "pause"

    cooler_state = DigitalPhysiologyState(**still_hot["state"])
    recovering = None
    for _ in range(3):
        recovering = regulator.update(
            cooler_state,
            observation(cpu_load=0.0, cooling=1.0, task_load=0.0),
        )
        cooler_state = DigitalPhysiologyState(**recovering["state"])
        if recovering["state"]["control_state"] in {"recovering", "normal"}:
            break
    assert recovering is not None
    assert recovering["state"]["control_state"] in {"recovering", "normal"}

    if recovering["state"]["control_state"] == "recovering":
        resumed = regulator.update(
            DigitalPhysiologyState(**recovering["state"]),
            observation(cpu_load=0.0, cooling=1.0, task_load=0.0),
        )
        assert resumed["state"]["control_state"] == "normal"


def test_high_noise_suppresses_exploration_without_changing_authority():
    regulator = DigitalHomeostasis()
    state = DigitalPhysiologyState()
    low_noise = regulator.update(state, observation(noise_risk=0.0))
    high_noise = regulator.update(state, observation(noise_risk=1.0))

    assert high_noise["regulation"]["exploration_budget"] <= low_noise["regulation"]["exploration_budget"]
    assert high_noise["regulation"]["authorization_granted"] is False
    assert high_noise["side_effects"]["work_dispatched"] is False


def test_observations_reject_boolean_and_nonfinite_values():
    with pytest.raises(DigitalPhysiologyError):
        observation(cpu_load=True)
    with pytest.raises(DigitalPhysiologyError):
        observation(thermal_pressure=float("nan"))
    with pytest.raises(DigitalPhysiologyError):
        observation(source=[])
    with pytest.raises(DigitalPhysiologyError):
        observation(cpu_load=10**1000)


def test_state_rejects_invalid_control_and_out_of_range_values():
    with pytest.raises(DigitalPhysiologyError):
        DigitalPhysiologyState(energy_reserve=1.1)
    with pytest.raises(DigitalPhysiologyError):
        DigitalPhysiologyState(control_state="happy")


def test_configuration_rejects_inconsistent_hysteresis_thresholds():
    with pytest.raises(DigitalPhysiologyError):
        PhysiologyConfig(
            low_energy_threshold=0.6,
            resume_energy_threshold=0.4,
        )
    with pytest.raises(DigitalPhysiologyError):
        PhysiologyConfig(
            high_thermal_threshold=0.7,
            critical_pressure_threshold=0.6,
        )


def test_report_is_json_compatible_and_contains_no_subjective_claim():
    result = DigitalHomeostasis().update(
        DigitalPhysiologyState(), observation()
    )
    assert "_next_state_object" not in result
    assert result["observation"]["authenticated"] is False
    assert result["regulation"]["advisory_only"] is True
    assert result["regulation"]["authorization_granted"] is False
    assert result["side_effects"]["hardware_read"] is False
    assert any("not emotions" in item for item in result["interpretation_limits"])
