from __future__ import annotations

import pytest

from agent.store import EventSequenceConflict, KnowledgeStore
from experiments.digital_physiology import DigitalHomeostasis, PhysiologyConfig, ResourceObservation
from experiments.persistent_digital_lifecycle import (
    ContinuousLifecycleConflict,
    ContinuousLifecycleError,
    PersistentDigitalLifecycle,
)


def sample_observation(**overrides):
    values = {
        "cpu_load": 0.25,
        "memory_pressure": 0.20,
        "thermal_pressure": 0.15,
        "energy_drain": 0.10,
        "cooling": 0.70,
        "recharge": 0.50,
        "task_load": 0.20,
        "unresolved_uncertainty": 0.80,
        "expected_learning_progress": 0.70,
        "noise_risk": 0.10,
        "source": "simulated",
    }
    values.update(overrides)
    return ResourceObservation(**values)


def test_recover_returns_explicit_unpersisted_baseline(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    lifecycle = PersistentDigitalLifecycle(store)

    result = lifecycle.recover()

    assert result["version"] == 0
    assert result["persisted"] is False
    assert result["state_origin"] == "default_initial_condition"
    assert result["state"]["cycle"] == 0
    assert result["authorization_granted"] is False
    assert result["work_dispatched"] is False
    assert store.count_events(PersistentDigitalLifecycle.EVENT_TYPE) == 0


def test_advance_persists_and_new_instance_recovers_same_state(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    first = PersistentDigitalLifecycle(store)

    committed = first.advance(sample_observation())

    assert committed["version"] == 1
    assert committed["persisted"] is True
    assert committed["state"]["cycle"] == 1
    assert committed["observation_provenance"]["epistemic_state"] == "simulated"
    assert committed["authorization_granted"] is False
    assert committed["work_dispatched"] is False

    recovered = PersistentDigitalLifecycle(store).recover()

    assert recovered["version"] == committed["version"]
    assert recovered["event_id"] == committed["event_id"]
    assert recovered["state"] == committed["state"]
    assert recovered["persisted"] is True
    assert recovered["state_origin"] == "persisted_snapshot"
    assert store.count_events(PersistentDigitalLifecycle.EVENT_TYPE) == 1


def test_caller_observation_is_not_misrepresented_as_authenticated_sensor_data(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    lifecycle = PersistentDigitalLifecycle(store)

    result = lifecycle.advance(sample_observation(source="caller_observed"))

    assert result["observation_provenance"]["epistemic_state"] == "caller_reported"
    assert result["observation_provenance"]["authenticated"] is False


def test_stale_expected_version_is_rejected_without_extra_event(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    lifecycle = PersistentDigitalLifecycle(store)
    lifecycle.advance(sample_observation(), expected_version=0)

    with pytest.raises(ContinuousLifecycleConflict):
        lifecycle.advance(sample_observation(), expected_version=0)

    assert store.count_events(PersistentDigitalLifecycle.EVENT_TYPE) == 1
    assert lifecycle.recover()["version"] == 1


def test_atomic_versioned_event_rejects_concurrent_stale_writer(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    first = store.record_versioned_event(
        "test.versioned", "test.versioned", 0, {"value": "first"}
    )

    assert first["sequence"] == 1
    with pytest.raises(EventSequenceConflict):
        store.record_versioned_event(
            "test.versioned", "test.versioned", 0, {"value": "stale"}
        )

    events = store.list_events(limit=10, event_type="test.versioned")
    assert len(events) == 1
    assert events[0]["payload"]["value"] == "first"
    assert events[0]["payload"]["sequence"] == 1


@pytest.mark.parametrize("expected", [-1, True, 1.5, "0"])
def test_invalid_expected_version_is_rejected(tmp_path, expected):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    lifecycle = PersistentDigitalLifecycle(store)

    with pytest.raises(ContinuousLifecycleError):
        lifecycle.advance(sample_observation(), expected_version=expected)



def test_non_json_event_payload_does_not_advance_sequence(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")

    with pytest.raises(ValueError):
        store.record_versioned_event(
            "test.versioned", "test.versioned", 0, {"not_json": float("nan")}
        )

    committed = store.record_versioned_event(
        "test.versioned", "test.versioned", 0, {"valid": True}
    )
    assert committed["sequence"] == 1
    assert store.count_events("test.versioned") == 1


def test_recovery_fails_closed_on_malformed_latest_snapshot(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    lifecycle = PersistentDigitalLifecycle(store)
    store.record_event(
        PersistentDigitalLifecycle.EVENT_TYPE,
        {"schema": "unexpected.schema", "version": 1, "state": {}},
    )

    with pytest.raises(ContinuousLifecycleError):
        lifecycle.recover()



def test_recovery_fails_closed_when_state_cycle_and_stream_version_diverge(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    lifecycle = PersistentDigitalLifecycle(store)
    baseline = lifecycle._initial_state()
    store.record_versioned_event(
        PersistentDigitalLifecycle.EVENT_TYPE,
        PersistentDigitalLifecycle.SEQUENCE_KEY,
        0,
        {
            "schema": PersistentDigitalLifecycle.SCHEMA,
            "schema_version": PersistentDigitalLifecycle.SCHEMA_VERSION,
            "lifecycle_version": PersistentDigitalLifecycle.VERSION,
            "homeostasis": lifecycle._homeostasis_snapshot(),
            "state": baseline,
        },
        sequence_field="version",
    )

    with pytest.raises(ContinuousLifecycleError, match="diverge"):
        lifecycle.recover()


def test_recovery_fails_closed_when_homeostasis_configuration_changes(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    original = PersistentDigitalLifecycle(store)
    committed = original.advance(sample_observation())
    assert committed["homeostasis_config_sha256"]

    changed_homeostasis = DigitalHomeostasis(
        PhysiologyConfig(energy_drain_gain=0.20)
    )
    changed = PersistentDigitalLifecycle(store, changed_homeostasis)
    with pytest.raises(ContinuousLifecycleError, match="Configuração de homeostase diverge"):
        changed.recover()


def test_snapshot_rejects_unsupported_schema_version(tmp_path):
    store = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    lifecycle = PersistentDigitalLifecycle(store)
    payload = {
        "schema": PersistentDigitalLifecycle.SCHEMA,
        "schema_version": 999,
        "lifecycle_version": PersistentDigitalLifecycle.VERSION,
        "homeostasis": lifecycle._homeostasis_snapshot(),
        "version": 1,
        "state": lifecycle._initial_state(),
    }
    store.record_event(PersistentDigitalLifecycle.EVENT_TYPE, payload)
    with pytest.raises(ContinuousLifecycleError, match="Versão de esquema"):
        lifecycle.recover()
