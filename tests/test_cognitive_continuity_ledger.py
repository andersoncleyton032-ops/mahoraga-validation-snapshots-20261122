from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.cognitive_continuity import (
    CognitiveContinuityConflict,
    CognitiveContinuityLedger,
)
from agent.cognitive_fabric import CognitiveFabric, SignalDraft
from agent.store import KnowledgeStore


def make_workspace():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["core", "language"],
        verified_relationships={},
    )
    workspace = fabric.new_workspace(metadata={"request_characters": 42})
    workspace.put(
        "private.artifact",
        {"document": "NEVER_STORE_PRIVATE_ARTIFACT_VALUE"},
        source="core",
    )
    fabric.publish(
        workspace,
        SignalDraft(
            topic="request.received",
            source="core",
            target="language",
            payload={"text": "NEVER_STORE_PRIVATE_SIGNAL_PAYLOAD"},
            evidence_refs=("NEVER_STORE_PRIVATE_EVIDENCE_REF",),
        ),
    )
    workspace.record_stage(
        "language.parse",
        "language",
        status="completed",
        duration_ms=10.0,
    )
    return workspace


def test_ledger_persists_only_redacted_record_in_canonical_store(tmp_path):
    store = KnowledgeStore(tmp_path / "continuity.sqlite3")
    ledger = CognitiveContinuityLedger(store)
    workspace = make_workspace()
    result = ledger.record_terminal_cycle(
        workspace,
        "completed",
    )

    assert result["status"] == "recorded"
    assert result["duplicate"] is False
    assert result["persistence"] == "canonical_knowledge_store"
    events = store.list_events(
        limit=10,
        event_type=CognitiveContinuityLedger.EVENT_TYPE,
    )
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["correlation_id"] == workspace.correlation_id
    serialized = json.dumps(payload, ensure_ascii=False)
    for secret in (
        "NEVER_STORE_PRIVATE_ARTIFACT_VALUE",
        "NEVER_STORE_PRIVATE_SIGNAL_PAYLOAD",
        "NEVER_STORE_PRIVATE_EVIDENCE_REF",
    ):
        assert secret not in serialized


def test_same_cycle_retry_is_idempotent_and_uses_first_commit_timestamp(tmp_path):
    store = KnowledgeStore(tmp_path / "continuity.sqlite3")
    ledger = CognitiveContinuityLedger(store)
    workspace = make_workspace()
    first = ledger.record_terminal_cycle(
        workspace, "completed"
    )
    second = ledger.record_terminal_cycle(
        workspace, "completed"
    )

    assert first["status"] == "recorded"
    assert second["status"] == "already_recorded"
    assert second["duplicate"] is True
    assert second["event_id"] == first["event_id"]
    assert len(store.list_events(event_type=ledger.EVENT_TYPE)) == 1


def test_same_cycle_cannot_be_replayed_with_a_different_terminal_outcome(tmp_path):
    store = KnowledgeStore(tmp_path / "continuity.sqlite3")
    ledger = CognitiveContinuityLedger(store)
    workspace = make_workspace()
    ledger.record_terminal_cycle(
        workspace, "completed"
    )
    with pytest.raises(CognitiveContinuityConflict, match="conteúdo terminal diferente"):
        ledger.record_terminal_cycle(
            workspace, "failed"
        )
    assert len(store.list_events(event_type=ledger.EVENT_TYPE)) == 1


def test_concurrent_duplicate_writes_commit_exactly_one_event(tmp_path):
    store = KnowledgeStore(tmp_path / "continuity.sqlite3")
    ledger = CognitiveContinuityLedger(store)
    workspace = make_workspace()

    def record(_):
        return ledger.record_terminal_cycle(workspace, "completed")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(record, range(8)))

    assert sum(result["status"] == "recorded" for result in results) == 1
    assert sum(result["status"] == "already_recorded" for result in results) == 7
    assert len(store.list_events(event_type=ledger.EVENT_TYPE)) == 1


def test_recent_cycles_recover_after_store_reopen(tmp_path):
    database = tmp_path / "continuity.sqlite3"
    first_store = KnowledgeStore(database)
    first_ledger = CognitiveContinuityLedger(first_store)
    workspace = make_workspace()
    first_ledger.record_terminal_cycle(
        workspace, "deferred"
    )

    reopened_store = KnowledgeStore(database)
    reopened_ledger = CognitiveContinuityLedger(reopened_store)
    recovered = reopened_ledger.recent_cycles(limit=10)

    assert len(recovered) == 1
    assert recovered[0]["record"]["cycle"]["correlation_id"] == workspace.correlation_id
    assert recovered[0]["record"]["outcome"] == "deferred"
    stored_event = reopened_store.list_events(
        limit=1,
        event_type=CognitiveContinuityLedger.EVENT_TYPE,
    )[0]
    assert recovered[0]["record"]["cycle"]["completed_at"] == stored_event["created_at"]


def test_ledger_rejects_non_workspace_and_invalid_history_limits(tmp_path):
    ledger = CognitiveContinuityLedger(KnowledgeStore(tmp_path / "continuity.sqlite3"))
    with pytest.raises(ValueError, match="CognitiveWorkspace"):
        ledger.record_terminal_cycle(object(), "completed")
    for invalid in (0, 101, True, "10"):
        with pytest.raises(ValueError, match="limit"):
            ledger.recent_cycles(invalid)


def test_snapshot_is_bounded_and_redacted_for_self_model(tmp_path):
    store = KnowledgeStore(tmp_path / "continuity.sqlite3")
    ledger = CognitiveContinuityLedger(store)
    fabric = CognitiveFabric()
    components = ["core"] + [f"component_{index}" for index in range(20)]
    fabric.configure_connectome(component_ids=components, verified_relationships={})

    for cycle_index in range(3):
        workspace = fabric.new_workspace()
        for index in range(20):
            fabric.publish(
                workspace,
                SignalDraft(
                    topic=f"topic.{index}",
                    source=f"component_{index}",
                    target="core",
                    payload={"private": "NEVER_PERSIST_PAYLOAD"},
                ),
            )
        ledger.record_terminal_cycle(
            workspace,
            "completed",
        )

    snapshot = ledger.snapshot(limit=2)
    assert snapshot["status"] == "available"
    assert snapshot["cycle_count"] == 2
    assert snapshot["truncated"] is True
    assert snapshot["outcomes"] == {"completed": 2}
    assert len(snapshot["recent_cycles"][0]["topics_observed"]) == 16
    assert snapshot["recent_cycles"][0]["topics_truncated"] is True
    assert len(snapshot["recent_cycles"][0]["participating_components"]) == 16
    assert snapshot["recent_cycles"][0]["components_truncated"] is True
    assert "NEVER_PERSIST_PAYLOAD" not in json.dumps(snapshot)
    with pytest.raises(ValueError, match="limit"):
        ledger.snapshot(limit=0)


def test_distinct_concurrent_cycles_receive_monotonic_event_ids(tmp_path):
    store = KnowledgeStore(tmp_path / "continuity.sqlite3")
    ledger = CognitiveContinuityLedger(store)
    workspaces = [make_workspace() for _ in range(8)]

    def record(workspace):
        return ledger.record_terminal_cycle(workspace, "completed")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(record, workspaces))

    assert all(result["status"] == "recorded" for result in results)
    assert sorted(result["event_id"] for result in results) == list(range(1, 9))
    assert len(store.list_events(event_type=ledger.EVENT_TYPE)) == 8




def test_recovery_rejects_tampered_continuity_payload(tmp_path):
    store = KnowledgeStore(tmp_path / "continuity.sqlite3")
    ledger = CognitiveContinuityLedger(store)
    workspace = make_workspace()
    saved = ledger.record_terminal_cycle(workspace, "completed")

    with store._transaction() as db:
        row = db.execute(
            "SELECT payload_json FROM events WHERE id=?",
            (saved["event_id"],),
        ).fetchone()
        payload = json.loads(row["payload_json"])
        payload["record"]["focus"]["topics_observed"].append("forged.topic")
        db.execute(
            "UPDATE events SET payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), saved["event_id"]),
        )

    assert ledger.recent_cycles(limit=10) == []
