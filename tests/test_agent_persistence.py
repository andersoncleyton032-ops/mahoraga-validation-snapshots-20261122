import json

from agent import actions, lab, memory


def test_memory_round_trip_uses_configured_lab_path(tmp_path, monkeypatch):
    target = tmp_path / "memory" / "data.json"
    monkeypatch.setattr(memory, "MEMORY_FILE", target)

    memory.save_memory("adaptation", "validated")

    restored = memory.load_memory()
    assert restored["adaptation"]["value"] == "validated"
    assert restored["adaptation"]["updated_at"]
    assert target.is_file()


def test_memory_load_returns_empty_when_store_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "missing" / "data.json")
    assert memory.load_memory() == {}


def test_experiment_log_round_trip_uses_configured_lab_path(tmp_path, monkeypatch, capsys):
    target = tmp_path / "experiments" / "experiments.json"
    monkeypatch.setattr(lab, "LAB_FILE", target)

    lab.save_experiment(
        "Does the budget defer work?",
        "deterministic simulation",
        "deferred",
        "resource gate behaved as expected",
    )

    restored = lab.load_experiments()
    assert len(restored) == 1
    assert restored[0]["hypothesis"] == "Does the budget defer work?"
    assert restored[0]["result"] == "deferred"
    assert restored[0]["conclusion"] == "resource gate behaved as expected"
    assert target.is_file()

    lab.show_experiments()
    assert "EXPERIMENTO 1" in capsys.readouterr().out


def test_experiment_log_load_returns_empty_when_store_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "LAB_FILE", tmp_path / "missing" / "experiments.json")
    assert lab.load_experiments() == []


def test_activity_log_writes_only_to_configured_lab_path(tmp_path, monkeypatch, capsys):
    target = tmp_path / "logs" / "activity.log"
    monkeypatch.setattr(actions, "LOG_FILE", target)

    actions.register_activity("isolated persistence test")

    saved = target.read_text(encoding="utf-8")
    assert "isolated persistence test" in saved
    assert saved.endswith("\\n")
    assert "Atividade registrada" in capsys.readouterr().out


def test_persistence_files_are_valid_json_after_round_trip(tmp_path, monkeypatch):
    memory_target = tmp_path / "memory" / "data.json"
    lab_target = tmp_path / "experiments" / "experiments.json"
    monkeypatch.setattr(memory, "MEMORY_FILE", memory_target)
    monkeypatch.setattr(lab, "LAB_FILE", lab_target)

    memory.save_memory("json-check", "ok")
    lab.save_experiment("h", "m", "r", "c")

    assert isinstance(json.loads(memory_target.read_text(encoding="utf-8")), dict)
    assert isinstance(json.loads(lab_target.read_text(encoding="utf-8")), list)
