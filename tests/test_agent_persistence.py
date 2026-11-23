from agent import actions, lab, memory
from agent.store import KnowledgeStore


def isolated_store(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    monkeypatch.setattr(memory, "_STORE", store)
    monkeypatch.setattr(lab, "get_store", lambda: store)
    return store


def test_memory_round_trip_uses_the_shared_sqlite_store(tmp_path, monkeypatch):
    store = isolated_store(tmp_path, monkeypatch)

    memory.save_memory("adaptation", "validated", {"source": "test"})
    restored = memory.load_memory()

    assert restored["adaptation"]["value"] == "validated"
    assert restored["adaptation"]["metadata"] == {"source": "test"}
    assert store.integrity_check() == "ok"


def test_empty_memory_store_returns_empty_mapping(tmp_path, monkeypatch):
    store = isolated_store(tmp_path, monkeypatch)
    assert memory.load_memory() == {}
    assert store.counts()["memories"] == 0


def test_experiment_log_round_trip_uses_the_shared_sqlite_store(tmp_path, monkeypatch, capsys):
    store = isolated_store(tmp_path, monkeypatch)

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
    assert store.integrity_check() == "ok"

    lab.show_experiments()
    assert "EXPERIMENTO 1" in capsys.readouterr().out


def test_activity_log_writes_only_to_configured_lab_path(tmp_path, monkeypatch, capsys):
    target = tmp_path / "logs" / "activity.log"
    monkeypatch.setattr(actions, "LOG_FILE", target)

    actions.register_activity("isolated persistence test")

    saved = target.read_text(encoding="utf-8")
    assert "isolated persistence test" in saved
    assert saved.endswith("\n")
    assert "Atividade registrada" in capsys.readouterr().out


def test_memory_learning_and_experiment_events_survive_store_reopen(tmp_path, monkeypatch):
    store = isolated_store(tmp_path, monkeypatch)
    memory.save_memory("persistent", {"value": 42})
    lab.save_experiment("h", "m", "r", "c")

    reopened = KnowledgeStore(tmp_path / "memory.sqlite3")
    assert reopened.load_memories()["persistent"]["value"] == {"value": 42}
    assert reopened.list_experiments(limit=10)[0]["conclusion"] == "c"
    assert reopened.integrity_check() == "ok"
