import json
import sqlite3
import tempfile
import unittest

import pytest
from pathlib import Path
from agent.store import KnowledgeStore


class TestKnowledgeStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = KnowledgeStore(self.root / "db.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_memory_round_trip(self):
        self.store.save_memory("identity", {"name": "Mahoraga"})
        self.assertEqual(self.store.load_memories()["identity"]["value"], {"name": "Mahoraga"})

    def test_memory_rejects_empty_key(self):
        with self.assertRaises(ValueError):
            self.store.save_memory("", "x")

    def test_event_is_persistent(self):
        self.store.record_event("test.event", {"ok": True})
        self.assertEqual(self.store.list_events(1)[0]["payload"], {"ok": True})

    def test_observation_validates_confidence(self):
        with self.assertRaises(ValueError):
            self.store.record_observation("test", "subject", {}, "unit", 1.5)

    def test_observation_round_trip_and_category_filter(self):
        first_id = self.store.record_observation(
            "self_inquiry", "Como retomar após reinicialização?",
            {"status": "open_question"}, "test", limitations=["não validada"]
        )
        self.store.record_observation(
            "other", "Outra observação", {"value": 1}, "test"
        )

        observations = self.store.list_observations(
            limit=10, category="self_inquiry"
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["id"], first_id)
        self.assertEqual(observations[0]["subject"], "Como retomar após reinicialização?")
        self.assertEqual(observations[0]["data"]["status"], "open_question")
        self.assertEqual(observations[0]["limitations"], ["não validada"])

    def test_list_observations_rejects_invalid_limits_and_categories(self):
        for invalid in (True, 0, 1001, "10"):
            with self.assertRaises(ValueError):
                self.store.list_observations(limit=invalid)
        with self.assertRaises(ValueError):
            self.store.list_observations(category=" ")

    def test_experiment_round_trip(self):
        self.store.record_experiment("h", "m", "r", "c")
        self.assertEqual(self.store.list_experiments(1)[0]["conclusion"], "c")

    def test_legacy_memory_import_is_idempotent(self):
        source = self.root / "legacy.json"
        source.write_text(json.dumps({"old": {"value": "preserved", "updated_at": "then"}}), encoding="utf-8")
        first = self.store.import_legacy_file(source, "memory")
        second = self.store.import_legacy_file(source, "memory")
        self.assertEqual(first["count"], 1)
        self.assertEqual(second["status"], "already_imported")
        self.assertEqual(self.store.load_memories()["old"]["value"], "preserved")

    def test_integrity_check(self):
        self.assertEqual(self.store.integrity_check(), "ok")

    def test_installation_registry_is_idempotent(self):
        record = {"installation_id": "termux:git:2.56", "name": "git", "version": "2.56",
                  "method": "termux_pkg", "source_url": None, "source_ref": "Termux official repository",
                  "installed_at": None, "purpose": "Version control", "verification": "version_observed"}
        self.assertTrue(self.store.record_installation(**record))
        self.assertFalse(self.store.record_installation(**record))
        self.assertEqual(len(self.store.list_installations()), 1)



    def test_observation_and_event_are_atomic(self):
        result = self.store.record_observation_and_event(
            "test", "subject", {"ok": True}, "unit", "test.atomic")
        self.assertGreater(result["observation_id"], 0)
        self.assertGreater(result["event_id"], 0)
        with self.store._reader() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM observations").fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='test.atomic'"
            ).fetchone()[0], 1)

    def test_atomic_failure_rolls_back_both_records(self):
        with self.store._transaction() as db:
            db.execute("""CREATE TRIGGER reject_test_event
                BEFORE INSERT ON events
                WHEN NEW.event_type='test.rollback'
                BEGIN SELECT RAISE(ABORT, 'forced test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_observation_and_event(
                "test", "subject", {}, "unit", "test.rollback")
        with self.store._reader() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM observations").fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='test.rollback'"
            ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()



def test_get_memory_reads_one_entry_and_handles_missing_key(tmp_path):
    store = KnowledgeStore(tmp_path / "single-memory.sqlite3")
    store.save_memory(
        "research_plan:one",
        {"plan_id": "one", "status": "prepared"},
        metadata={"kind": "research_plan"},
    )

    entry = store.get_memory("research_plan:one")
    assert entry["value"] == {"plan_id": "one", "status": "prepared"}
    assert entry["metadata"] == {"kind": "research_plan"}
    assert store.get_memory("research_plan:missing") is None

    for invalid in ("", "x" * 201, None):
        try:
            store.get_memory(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Chave inválida aceita: {invalid!r}")



def test_save_memory_if_absent_is_atomic_and_idempotent(tmp_path):
    store = KnowledgeStore(tmp_path / "create-once.sqlite3")
    value = {"plan_id": "stable", "status": "prepared"}

    assert store.save_memory_if_absent(
        "research_plan:stable", value, {"kind": "research_plan"}
    ) is True
    assert store.save_memory_if_absent(
        "research_plan:stable", {"plan_id": "different"}, {}
    ) is False

    entry = store.get_memory("research_plan:stable")
    assert entry["value"] == value
    assert entry["metadata"] == {"kind": "research_plan"}
    assert len(store.list_events(event_type="memory.saved")) == 1



def test_record_event_once_is_idempotent_across_store_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "event-idempotency.sqlite3"
    stores = [KnowledgeStore(db_path) for _ in range(4)]

    def submit(store):
        return store.record_event_once(
            "adaptive.experience.recorded",
            "research-plan-result:research-" + "a" * 24,
            {"plan_id": "research-" + "a" * 24, "result_status": "completed"},
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(submit, stores))

    assert len({item["event_id"] for item in results}) == 1
    assert sum(item["created"] for item in results) == 1
    assert len(stores[0].list_events(
        event_type="adaptive.experience.recorded"
    )) == 1


def test_record_event_once_rejects_idempotency_key_payload_conflict(tmp_path):
    store = KnowledgeStore(tmp_path / "event-conflict.sqlite3")
    first = store.record_event_once(
        "test.once", "test-key", {"value": 1}
    )
    repeated = store.record_event_once(
        "test.once", "test-key", {"value": 1}
    )
    assert first["created"] is True
    assert repeated["created"] is False
    assert repeated["event_id"] == first["event_id"]

    with pytest.raises(ValueError, match="outro conteúdo"):
        store.record_event_once(
            "test.once", "test-key", {"value": 2}
        )
    assert len(store.list_events(event_type="test.once")) == 1



def test_existing_schema_v3_database_upgrades_to_v6_without_data_loss(tmp_path):
    db_path = tmp_path / "legacy-v3.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE memories (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        );
        INSERT INTO memories(
            key,value_json,metadata_json,created_at,updated_at
        ) VALUES(
            'legacy-preserved','{"ok":true}','{}','2026-01-01','2026-01-01'
        );
        INSERT INTO schema_migrations VALUES
            (1,'2026-01-01','Initial unified knowledge store'),
            (2,'2026-01-01','Knowledge Engine document and chunk catalog'),
            (3,'2026-01-01','Persistent capability catalog');
        """
    )
    connection.commit()
    connection.close()

    store = KnowledgeStore(db_path)
    with store._reader() as db:
        versions = [
            row[0] for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        idempotency_table = db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='event_idempotency'"
        ).fetchone()
        sequence_table = db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='event_sequences'"
        ).fetchone()
        lab_table = db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='lab_experiments'"
        ).fetchone()

    assert versions == [1, 2, 3, 4, 5, 6]
    assert idempotency_table is not None
    assert sequence_table is not None
    assert lab_table is not None
    assert store.load_memories()["legacy-preserved"]["value"] == {"ok": True}

    event = store.record_event_once(
        "test.migrated", "migration-v4-check", {"ready": True}
    )
    assert event["created"] is True


def test_sequenced_events_allocate_unique_indexes_across_store_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "sequenced-events.sqlite3"
    stores = [KnowledgeStore(db_path) for _ in range(4)]
    total = 48

    def submit(index):
        store = stores[index % len(stores)]
        return store.record_sequenced_event(
            "conversation.exchange.recorded",
            "conversation.exchange:session-1",
            {"session_id": "session-1", "summary": f"exchange-{index}"},
            sequence_field="exchange_index",
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(submit, range(total)))

    sequences = sorted(item["sequence"] for item in results)
    events = stores[0].list_events(
        limit=100, event_type="conversation.exchange.recorded"
    )
    stored = sorted(item["payload"]["exchange_index"] for item in events)

    assert sequences == list(range(1, total + 1))
    assert stored == list(range(1, total + 1))
    assert len({item["event_id"] for item in results}) == total


def test_sequenced_event_rejects_payload_supplied_sequence(tmp_path):
    store = KnowledgeStore(tmp_path / "sequenced-invalid.sqlite3")
    with pytest.raises(ValueError, match="não pode definir"):
        store.record_sequenced_event(
            "test.sequence",
            "test:key",
            {"sequence": 99},
        )
    assert store.list_events(event_type="test.sequence") == []


def test_save_memory_and_audit_event_commit_atomically(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-atomic.sqlite3")
    with store._transaction() as db:
        db.execute("""
            CREATE TRIGGER reject_memory_saved_event
            BEFORE INSERT ON events
            WHEN NEW.event_type = 'memory.saved'
            BEGIN
                SELECT RAISE(ABORT, 'injected audit failure');
            END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="injected audit failure"):
        store.save_memory("atomic-key", {"value": "must rollback"})

    assert store.get_memory("atomic-key") is None
    assert store.list_events(event_type="memory.saved") == []


@pytest.mark.parametrize(
    "confidence",
    [True, False, 10 ** 10000],
    ids=["boolean-true", "boolean-false", "unrepresentable-huge-integer"],
)
def test_observation_confidence_rejects_boolean_and_unrepresentable_values(
    tmp_path, confidence
):
    store = KnowledgeStore(tmp_path / "confidence-validation.sqlite3")

    with pytest.raises(ValueError, match="número finito"):
        store.record_observation(
            category="test",
            subject="confidence",
            data={"value": 1},
            source="unit-test",
            confidence=confidence,
        )

    assert store.list_observations(category="test") == []


def test_atomic_observation_event_validates_event_contract(tmp_path):
    store = KnowledgeStore(tmp_path / "observation-event-validation.sqlite3")

    with pytest.raises(ValueError, match="severity"):
        store.record_observation_and_event(
            category="test",
            subject="subject",
            data={"value": 1},
            source="unit-test",
            event_type="test.event",
            severity="",
        )

    with pytest.raises(ValueError, match="event_payload"):
        store.record_observation_and_event(
            category="test",
            subject="subject",
            data={"value": 1},
            source="unit-test",
            event_type="test.event",
            event_payload=[],
        )

    assert store.list_observations(category="test") == []
    assert store.list_events(event_type="test.event") == []


def test_record_event_rejects_non_string_type_without_type_error(tmp_path):
    store = KnowledgeStore(tmp_path / "event-validation.sqlite3")

    with pytest.raises(ValueError, match="Tipo de evento"):
        store.record_event(123, {})

    assert store.list_events() == []

def test_memory_metadata_listing_never_returns_values_and_is_bounded(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-metadata.sqlite3")
    store.save_memory(
        "private:credential-like",
        {"secret_payload": "must-not-be-returned"},
        metadata={"kind": "test"},
    )
    store.save_memory(
        "public:summary",
        {"detail": "also-not-returned"},
        metadata={"kind": "summary"},
    )

    records = store.list_memory_metadata(limit=1)

    assert len(records) == 1
    assert set(records[0]) == {"key", "created_at", "updated_at"}
    assert "value" not in records[0]
    assert store.count_memories() == 2
    assert "must-not-be-returned" not in repr(records)

    for invalid in (True, 0, 1001, "10"):
        with pytest.raises(ValueError):
            store.list_memory_metadata(limit=invalid)


def test_event_metadata_listing_never_returns_payloads(tmp_path):
    store = KnowledgeStore(tmp_path / "event-metadata.sqlite3")
    store.record_event(
        "private.event",
        {"secret_payload": "must-not-be-returned"},
    )

    records = store.list_event_metadata(limit=10)

    assert len(records) == 1
    assert set(records[0]) == {"id", "event_type", "severity", "created_at"}
    assert "payload" not in records[0]
    assert "must-not-be-returned" not in repr(records)
    assert store.count_events("private.event") == 1

    for invalid in (True, 0, 1001, "10"):
        with pytest.raises(ValueError):
            store.list_event_metadata(limit=invalid)
    with pytest.raises(ValueError):
        store.list_event_metadata(event_type=" ")


def test_record_event_once_can_compare_and_swap_latest_event_revision(tmp_path):
    store = KnowledgeStore(tmp_path / "event-cas.sqlite3")
    initial_id = store.record_event("executive.focus", {"goal_id": None})

    updated = store.record_event_once(
        "executive.focus",
        "focus-revision-1",
        {"goal_id": "goal-a"},
        expected_latest_event_type="executive.focus",
        expected_latest_event_id=initial_id,
    )
    assert updated["created"] is True

    with pytest.raises(ValueError, match="Revisão do evento alterada"):
        store.record_event_once(
            "executive.focus",
            "focus-stale-revision",
            {"goal_id": "goal-b"},
            expected_latest_event_type="executive.focus",
            expected_latest_event_id=initial_id,
        )
    with pytest.raises(ValueError, match="Revisão do evento alterada"):
        store.record_event_once(
            "executive.focus",
            "focus-initial-stale",
            {"goal_id": "goal-c"},
            expected_latest_event_type="executive.focus",
            expected_latest_event_id=None,
        )
