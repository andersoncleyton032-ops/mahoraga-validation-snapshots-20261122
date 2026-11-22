import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.store import KnowledgeStore


def make_store(tmp_path):
    return KnowledgeStore(tmp_path / "ledger.sqlite3")


def create(store, experiment_id="exp-001"):
    return store.create_lab_experiment(
        experiment_id,
        {
            "hypothesis": "A bounded hypothesis",
            "method": "deterministic regression experiment",
            "scope": "experiments/",
            "risk": "low",
            "resource_budget": {"runtime_ms": 500, "memory_mb": 16},
        },
        parent_digest="a" * 64,
    )


def transition(store, experiment_id, *, version, old, new, evidence=None, digest=None):
    return store.transition_lab_experiment(
        experiment_id,
        expected_version=version,
        expected_stage=old,
        new_stage=new,
        evidence=evidence or {"note": "synthetic test evidence"},
        candidate_digest=digest,
    )


def test_lab_experiment_ledger_persists_and_replays_after_reopen(tmp_path):
    store = make_store(tmp_path)
    created = create(store)
    transition(store, "exp-001", version=1, old="proposed", new="triaged")
    transition(store, "exp-001", version=2, old="triaged", new="sandboxed")
    digest = "b" * 64
    transition(
        store, "exp-001", version=3, old="sandboxed", new="tested",
        evidence={"tests_passed": 12, "tests_total": 12, "ci_run": "run-42"},
        digest=digest,
    )

    reopened = KnowledgeStore(store.db_path)
    current = reopened.get_lab_experiment("exp-001")
    history = reopened.get_lab_experiment_history("exp-001")
    audit = reopened.audit_lab_experiments()

    assert created["version"] == 1
    assert current["stage"] == "tested"
    assert current["version"] == 4
    assert current["candidate_digest"] == digest
    assert [item["sequence"] for item in history] == [1, 2, 3, 4]
    assert [item["to_stage"] for item in history] == [
        "proposed", "triaged", "sandboxed", "tested"
    ]
    assert audit == {"checked": 1, "valid": ["exp-001"], "invalid": [], "truncated": False}


def test_review_ready_requires_independent_review_reference(tmp_path):
    store = make_store(tmp_path)
    create(store)
    transition(store, "exp-001", version=1, old="proposed", new="triaged")
    transition(store, "exp-001", version=2, old="triaged", new="sandboxed")
    transition(
        store, "exp-001", version=3, old="sandboxed", new="tested",
        evidence={"tests_passed": 2, "tests_total": 2}, digest="c" * 64,
    )
    with pytest.raises(ValueError, match="revisão independente"):
        transition(
            store, "exp-001", version=4, old="tested", new="review_ready",
            evidence={"tests_passed": 2, "tests_total": 2},
        )

    result = transition(
        store, "exp-001", version=4, old="tested", new="review_ready",
        evidence={"independent_review_ref": "review:independent-001"},
    )
    assert result["stage"] == "review_ready"
    assert store.audit_lab_experiments()["invalid"] == []
    assert "promoted" not in store.LAB_EXPERIMENT_STAGES


@pytest.mark.parametrize(
    "passed,total,digest",
    [(0, 0, "d" * 64), (1, 2, "d" * 64), (2, 2, None)],
)
def test_tested_stage_requires_complete_tests_and_candidate_digest(
    tmp_path, passed, total, digest
):
    store = make_store(tmp_path)
    create(store)
    transition(store, "exp-001", version=1, old="proposed", new="triaged")
    transition(store, "exp-001", version=2, old="triaged", new="sandboxed")
    with pytest.raises(ValueError, match="todos os testes aprovados"):
        transition(
            store, "exp-001", version=3, old="sandboxed", new="tested",
            evidence={"tests_passed": passed, "tests_total": total}, digest=digest,
        )
    assert store.get_lab_experiment("exp-001")["stage"] == "sandboxed"
    assert len(store.get_lab_experiment_history("exp-001")) == 3


def test_illegal_transition_and_stale_version_are_rejected(tmp_path):
    store = make_store(tmp_path)
    create(store)
    with pytest.raises(ValueError, match="não permitida"):
        transition(store, "exp-001", version=1, old="proposed", new="tested")
    transition(store, "exp-001", version=1, old="proposed", new="triaged")
    with pytest.raises(ValueError, match="Conflito de versão"):
        transition(store, "exp-001", version=1, old="proposed", new="rejected")
    assert store.get_lab_experiment("exp-001")["version"] == 2


def test_concurrent_compare_and_swap_allows_only_one_transition(tmp_path):
    first = make_store(tmp_path)
    second = KnowledgeStore(first.db_path)
    create(first)

    def submit(store, target):
        try:
            return transition(
                store, "exp-001", version=1, old="proposed", new=target
            )["stage"]
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda pair: submit(*pair),
            [(first, "triaged"), (second, "rejected")],
        ))
    assert sorted(results).count("conflict") == 1
    assert sum(value in {"triaged", "rejected"} for value in results) == 1
    assert len(first.get_lab_experiment_history("exp-001")) == 2


def test_create_is_atomic_when_initial_event_insert_fails(tmp_path):
    store = make_store(tmp_path)
    with store._transaction() as db:
        db.execute("""
            CREATE TRIGGER reject_lab_create_event
            BEFORE INSERT ON lab_experiment_events
            BEGIN SELECT RAISE(ABORT, 'injected ledger failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="injected ledger failure"):
        create(store)
    assert store.get_lab_experiment("exp-001") is None
    assert store.audit_lab_experiments()["checked"] == 0


def test_transition_is_atomic_when_history_append_fails(tmp_path):
    store = make_store(tmp_path)
    create(store)
    with store._transaction() as db:
        db.execute("""
            CREATE TRIGGER reject_lab_transition_event
            BEFORE INSERT ON lab_experiment_events
            WHEN NEW.event_type = 'transition'
            BEGIN SELECT RAISE(ABORT, 'injected transition failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="injected transition failure"):
        transition(store, "exp-001", version=1, old="proposed", new="triaged")
    current = store.get_lab_experiment("exp-001")
    assert current["stage"] == "proposed"
    assert current["version"] == 1
    assert len(store.get_lab_experiment_history("exp-001")) == 1


def test_current_record_metadata_tampering_is_detected(tmp_path):
    store = make_store(tmp_path)
    create(store)
    with store._transaction() as db:
        db.execute(
            "UPDATE lab_experiments SET stage='tested' WHERE experiment_id='exp-001'"
        )
    with pytest.raises(sqlite3.DatabaseError, match="Checksum do registro"):
        store.get_lab_experiment("exp-001")
    audit = store.audit_lab_experiments()
    assert audit["invalid"][0]["experiment_id"] == "exp-001"


def test_event_metadata_tampering_is_detected(tmp_path):
    store = make_store(tmp_path)
    create(store)
    with store._transaction() as db:
        db.execute(
            "UPDATE lab_experiment_events SET to_stage='triaged' "
            "WHERE experiment_id='exp-001' AND sequence=1"
        )
    with pytest.raises(sqlite3.DatabaseError, match="Checksum do histórico"):
        store.get_lab_experiment_history("exp-001")
    assert store.audit_lab_experiments()["invalid"]


def test_payload_validation_rejects_non_json_nonfinite_deep_and_oversized_values(tmp_path):
    store = make_store(tmp_path)
    invalid_payloads = [
        {"bad": object()},
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"bad": "x" * 16_385},
        {"bad": [[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]]},
        {"bad": ["x" * 16_384 for _ in range(5)]},
    ]
    for index, payload in enumerate(invalid_payloads):
        with pytest.raises(ValueError):
            store.create_lab_experiment(f"invalid-{index}", payload)
    assert store.list_lab_experiments() == []


def test_experiment_ids_and_parent_digests_are_validated(tmp_path):
    store = make_store(tmp_path)
    for invalid in ("../escape", "with space", "", "x" * 129):
        with pytest.raises(ValueError):
            store.create_lab_experiment(invalid, {})
    with pytest.raises(ValueError, match="SHA-256"):
        store.create_lab_experiment("bad-parent", {}, parent_digest="not-a-digest")


def test_schema_v5_database_upgrades_to_v6_without_losing_existing_records(tmp_path):
    store = make_store(tmp_path)
    store.save_memory("preserve-me", {"ok": True})
    with store._transaction() as db:
        db.execute("DROP TABLE lab_experiment_events")
        db.execute("DROP TABLE lab_experiments")
        db.execute("DELETE FROM schema_migrations WHERE version=6")
    reopened = KnowledgeStore(store.db_path)
    assert reopened.load_memories()["preserve-me"]["value"] == {"ok": True}
    with reopened._reader() as db:
        version = db.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0]
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert version == 6
    assert {"lab_experiments", "lab_experiment_events"} <= tables


def test_ledger_listing_is_bounded_and_reports_corruption(tmp_path):
    store = make_store(tmp_path)
    for index in range(3):
        store.create_lab_experiment(f"exp-{index}", {"index": index})
    assert len(store.list_lab_experiments(limit=2)) == 2
    assert store.audit_lab_experiments(limit=2)["truncated"] is True
    for invalid in (True, 0, 501, "2"):
        with pytest.raises(ValueError):
            store.list_lab_experiments(limit=invalid)


def test_concurrent_idempotent_creation_produces_one_record(tmp_path):
    stores = [KnowledgeStore(tmp_path / "concurrent-create.sqlite3") for _ in range(4)]
    payload = {"hypothesis": "same candidate", "method": "parallel replay"}

    def submit(index):
        return stores[index % len(stores)].create_lab_experiment_once(
            "shared-experiment", payload, parent_digest="e" * 64
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(submit, range(48)))

    assert sum(item["created"] for item in results) == 1
    assert sum(not item["created"] for item in results) == 47
    assert len(stores[0].list_lab_experiments()) == 1
    assert len(stores[0].get_lab_experiment_history("shared-experiment")) == 1


def test_history_sequence_gap_is_detected_and_reported(tmp_path):
    store = make_store(tmp_path)
    create(store)
    transition(store, "exp-001", version=1, old="proposed", new="triaged")
    transition(store, "exp-001", version=2, old="triaged", new="sandboxed")
    with store._transaction() as db:
        db.execute(
            "DELETE FROM lab_experiment_events "
            "WHERE experiment_id='exp-001' AND sequence=2"
        )
    with pytest.raises(sqlite3.DatabaseError, match="lacuna"):
        store.get_lab_experiment_history("exp-001")
    assert store.audit_lab_experiments()["invalid"]


def test_terminal_experiment_states_cannot_be_promoted_or_reopened(tmp_path):
    store = make_store(tmp_path)
    create(store)
    transition(store, "exp-001", version=1, old="proposed", new="rejected")
    with pytest.raises(ValueError, match="não permitida"):
        transition(store, "exp-001", version=2, old="rejected", new="proposed")
    assert store.get_lab_experiment("exp-001")["stage"] == "rejected"
