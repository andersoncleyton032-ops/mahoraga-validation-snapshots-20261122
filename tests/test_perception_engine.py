import json

import pytest

from agent.dharma import Dharma
from agent.hardware_intelligence import HardwareIntelligence
from agent.perception_engine import PerceptionEngine, PerceptionError
from agent.store import KnowledgeStore


def make_perception(tmp_path, sample_values=None):
    store = KnowledgeStore(tmp_path / "perception.sqlite3")
    calls = []
    sensors = ["Accelerometer", "Gyroscope"]

    def runner(argv, timeout):
        calls.append((list(argv), timeout))
        if argv == ["termux-sensor", "-l"]:
            return {
                "available": True,
                "returncode": 0,
                "stdout": json.dumps({"sensors": sensors}),
                "stderr": "",
            }
        selected = argv[2]
        values = sample_values if sample_values is not None else [0.1, 0.2, 0.3]
        return {
            "available": True,
            "returncode": 0,
            "stdout": json.dumps({
                selected: {"values": values, "accuracy": 3},
            }),
            "stderr": "",
        }

    engine = PerceptionEngine(
        store=store,
        hardware=HardwareIntelligence(root=tmp_path),
        dharma=Dharma(tmp_path),
        command_runner=runner,
    )
    return engine, store, calls


def test_inventory_is_read_only_and_reports_device_sensor_names(tmp_path):
    engine, store, calls = make_perception(tmp_path)

    result = engine.inventory()

    assert result["status"] == "available"
    assert result["sensors"] == ["Accelerometer", "Gyroscope"]
    assert result["continuous_sampling"] is False
    assert store.counts()["observations"] == 0
    assert calls == [(["termux-sensor", "-l"], 8)]


def test_sensor_sampling_is_single_shot_and_persists_provenance(tmp_path):
    engine, store, calls = make_perception(tmp_path)

    result = engine.sample_sensors(["Accelerometer"], delay_ms=750)

    assert result["status"] == "completed"
    assert len(result["sampled"]) == 1
    sample = result["sampled"][0]
    assert sample["values"] == [0.1, 0.2, 0.3]
    assert sample["accuracy"] == 3
    assert sample["sampling"]["sample_count"] == 1
    assert sample["sampling"]["continuous"] is False
    assert result["side_effects"]["sensor_stream_started"] is False
    assert result["side_effects"]["camera_opened"] is False
    assert result["side_effects"]["microphone_opened"] is False

    sample_commands = [argv for argv, _ in calls if argv[0] == "termux-sensor" and "-s" in argv]
    assert len(sample_commands) == 1
    assert "-n" in sample_commands[0]
    assert sample_commands[0][sample_commands[0].index("-n") + 1] == "1"
    assert "-a" not in sample_commands[0]

    observations = store.list_observations(limit=10, category="sensor_sample")
    events = store.list_events(limit=10, event_type="perception.sensor_sampled")
    assert len(observations) == 1
    assert len(events) == 1
    assert observations[0]["source"] == "PerceptionEngine.TermuxAPI"
    assert observations[0]["data"]["epistemic_state"] == "device_reported_not_independently_calibrated"


def test_unknown_sensor_is_rejected_before_sampling(tmp_path):
    engine, store, calls = make_perception(tmp_path)

    with pytest.raises(PerceptionError, match="não encontrados"):
        engine.sample_sensors(["Camera temperature"])

    assert len(calls) == 1
    assert store.counts()["observations"] == 0


def test_sensor_sampling_rejects_non_finite_values(tmp_path):
    engine, store, _ = make_perception(tmp_path, sample_values=[0.1, float("nan")])

    result = engine.sample_sensors(["Accelerometer"])

    assert result["status"] == "failed"
    assert result["sampled"] == []
    assert result["failures"][0]["status"] == "invalid_sample"
    assert store.counts()["observations"] == 0


def test_sensor_sampling_enforces_bounded_batch_and_delay(tmp_path):
    engine, _, _ = make_perception(tmp_path)

    with pytest.raises(PerceptionError, match="no máximo"):
        engine.sample_sensors(
            ["Accelerometer", "Gyroscope", "Accelerometer", "Gyroscope", "Extra"]
        )
    with pytest.raises(PerceptionError, match="delay_ms"):
        engine.sample_sensors(["Accelerometer"], delay_ms=0)


def test_sensor_sampling_rejects_ambiguous_partial_names(tmp_path):
    engine, store, calls = make_perception(tmp_path)
    original_runner = engine._command_runner

    def ambiguous_runner(argv, timeout):
        if argv == ["termux-sensor", "-l"]:
            calls.append((list(argv), timeout))
            return {
                "available": True,
                "returncode": 0,
                "stdout": json.dumps({
                    "sensors": ["Temperature", "Ambient Temperature"]
                }),
                "stderr": "",
            }
        return original_runner(argv, timeout)

    engine._command_runner = ambiguous_runner

    with pytest.raises(PerceptionError, match="mais de um sensor"):
        engine.sample_sensors(["Temperature"])

    assert len(calls) == 1
    assert store.counts()["observations"] == 0



def test_inventory_timeout_is_not_misreported_as_invalid_json(tmp_path):
    engine, _, _ = make_perception(tmp_path)
    engine._command_runner = lambda argv, timeout: {
        "available": True,
        "returncode": None,
        "status": "timeout",
        "stdout": "",
        "stderr": "timed out",
    }

    result = engine.inventory()

    assert result["available"] is False
    assert result["status"] == "timeout"


def test_sensor_parser_rejects_unrepresentably_large_integer():
    huge_integer = 10 ** 4000
    payload = json.dumps({
        "Accelerometer": {"values": [huge_integer], "accuracy": 3}
    })

    with pytest.raises(PerceptionError, match="representável"):
        PerceptionEngine._parse_sample(payload, "Accelerometer")
