import pytest

from agent.dharma import Dharma
from agent.memory_graph import MemoryGraphEngine, MemoryGraphError
from agent.store import KnowledgeStore


class FakeCognitive:
    def __init__(self, store):
        self.store = store
        self.dharma = Dharma()

    def _authorize(self, action):
        decision = self.dharma.evaluate(action)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        return decision


def test_memory_graph_relations_are_idempotent_unverified_and_event_backed(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-graph.sqlite3")
    graph = MemoryGraphEngine(FakeCognitive(store))
    first = store.record_event("test.episode", {"observation": "A"})
    second = store.record_event("test.episode", {"observation": "B"})
    before_tables = store.counts()

    result = graph.record_relation(
        first, "supports", second,
        context={"task": "association_test"},
        evidence_event_ids=[first, second],
    )
    duplicate = graph.record_relation(
        first, "supports", second,
        context={"task": "association_test"},
        evidence_event_ids=[second, first],
    )

    assert result["status"] == "recorded"
    assert duplicate["status"] == "already_recorded"
    assert result["event_id"] == duplicate["event_id"]
    assert result["verified"] is False
    assert result["epistemic_state"] == "candidate_unverified"
    related = graph.related_events(first, predicate="supports")
    assert related["count"] == 1
    assert related["neighbors"][0]["event_id"] == second
    assert related["neighbors"][0]["epistemic_state"] == "candidate_unverified"
    assert store.counts()["events"] == before_tables["events"] + 1
    assert store.SCHEMA_VERSION == 6
    assert store.count_events("memory.relation.proposed") == 1


def test_memory_graph_rejects_unknown_events_and_invalid_self_edges(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-graph-invalid.sqlite3")
    graph = MemoryGraphEngine(FakeCognitive(store))
    event_id = store.record_event("test.episode", {"observation": "A"})

    with pytest.raises(MemoryGraphError):
        graph.record_relation(event_id, "supports", event_id)
    with pytest.raises(MemoryGraphError):
        graph.record_relation(event_id, "supports", 999999)
    second_id = store.record_event("test.episode", {"observation": "B"})
    with pytest.raises(MemoryGraphError):
        graph.record_relation(event_id, "not a predicate", second_id)


def test_memory_interpretations_are_append_only_and_versioned_by_event_identity(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-interpretation.sqlite3")
    graph = MemoryGraphEngine(FakeCognitive(store))
    source_id = store.record_event("test.episode", {"sensor_reading": 7.5})
    supporting_id = store.record_event("test.context", {"context": "laboratory"})
    original = store.get_event(source_id)

    first = graph.record_interpretation(
        source_id,
        "Initial interpretation",
        rationale="First review",
        support_event_ids=[supporting_id],
    )
    first_duplicate = graph.record_interpretation(
        source_id,
        "Initial interpretation",
        rationale="First review",
        support_event_ids=[supporting_id],
    )
    second = graph.record_interpretation(
        source_id,
        "Revised interpretation",
        rationale="New evidence changed the reading",
        support_event_ids=[supporting_id],
        supersedes_interpretation_event_id=first["event_id"],
    )

    history = graph.list_interpretations(source_id)
    assert first["status"] == "recorded"
    assert first_duplicate["status"] == "already_recorded"
    assert first["event_id"] == first_duplicate["event_id"]
    assert second["status"] == "recorded"
    assert history["count"] == 2
    assert history["interpretations"][0]["event_id"] == first["event_id"]
    assert history["interpretations"][1]["supersedes_interpretation_event_id"] == first["event_id"]
    assert all(item["verified"] is False for item in history["interpretations"])
    assert store.get_event(source_id) == original
    assert history["source_event_mutated"] is False


def test_memory_graph_enforces_context_and_evidence_limits(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-graph-limits.sqlite3")
    graph = MemoryGraphEngine(FakeCognitive(store))
    event_ids = [
        store.record_event("test.episode", {"index": index})
        for index in range(20)
    ]
    with pytest.raises(MemoryGraphError):
        graph.record_relation(
            event_ids[0], "supports", event_ids[1],
            context={"large": "x" * 5000},
        )
    with pytest.raises(MemoryGraphError):
        graph.record_relation(
            event_ids[0], "supports", event_ids[1],
            evidence_event_ids=event_ids[2:18],
        )
    with pytest.raises(MemoryGraphError):
        graph.record_relation(
            event_ids[0], "supports", event_ids[1],
            context={1: "non-text-key"},
        )
    with pytest.raises(MemoryGraphError):
        graph.related_events(999999)


def test_memory_graph_uses_only_canonical_store_events_without_new_tables(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-graph-schema.sqlite3")
    graph = MemoryGraphEngine(FakeCognitive(store))
    with store._reader() as db:
        before = {
            row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    source = store.record_event("test.episode", {"x": 1})
    target = store.record_event("test.episode", {"x": 2})
    graph.record_relation(source, "related_to", target)
    graph.record_interpretation(source, "candidate meaning")
    with store._reader() as db:
        after = {
            row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert after == before
    assert graph.status()["storage"] == "canonical_knowledge_store_events"
    assert graph.status()["new_database_or_tables"] is False



def test_memory_graph_expansion_uses_bounded_bulk_event_reads(
    tmp_path, monkeypatch
):
    store = KnowledgeStore(tmp_path / "memory-graph-bulk.sqlite3")
    graph = MemoryGraphEngine(FakeCognitive(store))
    source_id = store.record_event("test.episode", {"observation": "source"})
    related_id = store.record_event("test.episode", {"observation": "related"})
    document_hash = "a" * 64
    chunk_hash = "b" * 64

    store.record_event(
        graph.RELATION_EVENT_TYPE,
        {
            "subject_event_id": source_id,
            "object_event_id": related_id,
            "predicate": "supports",
            "verified": False,
        },
    )
    store.record_event(
        graph.CHUNK_ANCHOR_EVENT_TYPE,
        {
            "source_event_id": source_id,
            "document_id": 1,
            "document_sha256": document_hash,
            "chunk_index": 0,
            "chunk_sha256": chunk_hash,
            "verified": False,
        },
    )
    initial_count = store.count_events()
    original_connect = store._connect
    connection_count = 0

    def counted_connect():
        nonlocal connection_count
        connection_count += 1
        return original_connect()

    def forbidden_single_read(event_id):
        pytest.fail("expand_chunk_associations used N+1 get_event() reads")

    monkeypatch.setattr(store, "_connect", counted_connect)
    monkeypatch.setattr(store, "get_event", forbidden_single_read)

    result = graph.expand_chunk_associations(
        [{
            "document_id": 1,
            "document_sha256": document_hash,
            "chunk_index": 0,
            "chunk_sha256": chunk_hash,
        }],
        max_related_events=10,
    )

    assert result["association_count"] == 1
    assert result["related_event_count"] == 1
    assert result["associations"][0]["source_event"]["id"] == source_id
    relation = result["associations"][0]["relations"][0]
    assert relation["event_id"] == related_id
    assert relation["event"]["payload"] == {"observation": "related"}
    assert relation["epistemic_state"] == "candidate_unverified"
    assert result["persistent_write_performed"] is False
    assert connection_count == 3
    assert store.count_events() == initial_count


def test_store_get_events_is_bounded_and_rejects_invalid_ids(tmp_path):
    store = KnowledgeStore(tmp_path / "bulk-events-validation.sqlite3")
    first = store.record_event("test.event", {"id": 1})
    second = store.record_event("test.event", {"id": 2})

    events = store.get_events([first, second, first, 999999])

    assert set(events) == {first, second}
    assert events[first]["payload"] == {"id": 1}
    assert events[second]["payload"] == {"id": 2}
    assert store.get_events([]) == {}

    for invalid in (True, 0, -1, 1.5, "1", 2**63):
        with pytest.raises(ValueError, match="event_id"):
            store.get_events([invalid])
    with pytest.raises(ValueError, match="3000"):
        store.get_events(list(range(1, 3002)))
