import hashlib

import pytest

from agent.cognitive_engine import CognitiveEngine
from agent.dharma import Dharma
from agent.knowledge_engine import KnowledgeEngine
from agent.memory_graph import MemoryGraphEngine, MemoryGraphError
from agent.store import KnowledgeStore


class FakeCognitive:
    def __init__(self, store):
        self.store = store
        self.knowledge = KnowledgeEngine(store)
        self.dharma = Dharma()

    def _authorize(self, action):
        decision = self.dharma.evaluate(action)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        return decision


def _fixture(tmp_path):
    store = KnowledgeStore(tmp_path / "associative-retrieval.sqlite3")
    knowledge = KnowledgeEngine(store)
    cognitive = CognitiveEngine(store=store, knowledge=knowledge, dharma=Dharma())
    source_event = store.record_event("test.episode", {"observation": "The Realme CPU became warm during a sustained test."})
    related_event = store.record_event("test.episode", {"observation": "The test was stopped after the charger was disconnected."})
    source = tmp_path / "thermal.md"
    source.write_text("The Realme CPU became warm during a sustained test. Monitor temperature and battery during long tests.", encoding="utf-8")
    imported = knowledge.import_document(source, subject="hardware")
    chunk = knowledge.list_chunks(imported["document_id"])[0]
    match = knowledge.search_chunks("Realme CPU temperature", limit=1)[0]
    return store, cognitive, source_event, related_event, imported, chunk, match


def test_chunk_lookup_is_read_only_and_hash_bound(tmp_path):
    store, cognitive, source, related, imported, chunk, match = _fixture(tmp_path)
    actual = cognitive.knowledge.get_chunk(imported["document_id"], chunk["chunk_index"])
    assert actual["chunk_sha256"] == hashlib.sha256(actual["content"].encode("utf-8")).hexdigest()
    assert actual["document_sha256"] == imported["sha256"]
    assert cognitive.knowledge.get_chunk(999999, 0) is None
    with pytest.raises(ValueError):
        cognitive.knowledge.get_chunk(True, 0)
    with pytest.raises(ValueError):
        cognitive.knowledge.get_chunk(imported["document_id"], -1)


def test_chunk_anchor_connects_retrieved_document_to_episode_without_promotion(tmp_path):
    store, cognitive, source, related, imported, chunk, match = _fixture(tmp_path)
    before = store.count_events()
    anchor = cognitive.memory_graph.record_chunk_anchor(source, imported["document_id"], chunk["chunk_index"], context={"reason": "same observation source"})
    duplicate = cognitive.memory_graph.record_chunk_anchor(source, imported["document_id"], chunk["chunk_index"], context={"reason": "same observation source"})
    edge = cognitive.memory_graph.record_relation(source, "related_to", related)
    assert anchor["status"] == "recorded"
    assert duplicate["status"] == "already_recorded"
    assert anchor["event_id"] == duplicate["event_id"]
    assert edge["verified"] is False
    expanded = cognitive.memory_graph.expand_chunk_associations([match], max_related_events=5)
    assert expanded["association_count"] == 1
    assert expanded["related_event_count"] == 1
    association = expanded["associations"][0]
    assert association["source_event"]["id"] == source
    assert association["chunk_sha256"] == match["chunk_sha256"]
    assert association["relations"][0]["event"]["id"] == related
    assert association["verified"] is False
    assert association["relations"][0]["verified"] is False
    assert expanded["persistent_write_performed"] is False
    assert store.count_events() == before + 2


def test_chunk_anchor_rejects_stale_or_unknown_chunk_identity(tmp_path):
    store, cognitive, source, related, imported, chunk, match = _fixture(tmp_path)
    with pytest.raises(MemoryGraphError, match="não existe ou não está preparado"):
        cognitive.memory_graph.record_chunk_anchor(source, 999999, 0)
    anchor = cognitive.memory_graph.record_chunk_anchor(source, imported["document_id"], 0)
    altered = dict(match, chunk_sha256="0" * 64)
    expanded = cognitive.memory_graph.expand_chunk_associations([altered])
    assert expanded["association_count"] == 0
    assert anchor["verified"] is False


def test_cognitive_retrieval_can_include_associations_without_writing(tmp_path):
    store, cognitive, source, related, imported, chunk, match = _fixture(tmp_path)
    cognitive.memory_graph.record_chunk_anchor(source, imported["document_id"], chunk["chunk_index"])
    cognitive.memory_graph.record_relation(source, "related_to", related)
    before = store.count_events()
    result = cognitive.retrieve_knowledge(
        "Realme CPU temperature", include_associations=True
    )
    assert result["result_count"] == 1
    assert result["associations"]["association_count"] == 1
    assert result["associations"]["related_event_count"] == 1
    assert result["memory_modified"] is False
    assert store.count_events() == before
    plain = cognitive.retrieve_knowledge("Realme CPU temperature")
    assert plain["associations"]["status"] == "not_requested"


def test_associative_expansion_is_bounded_and_read_authorized(tmp_path):
    store, cognitive, source, related, imported, chunk, match = _fixture(tmp_path)
    with pytest.raises(MemoryGraphError):
        cognitive.memory_graph.expand_chunk_associations([match] * 21)
    with pytest.raises(MemoryGraphError):
        cognitive.memory_graph.expand_chunk_associations([match], max_related_events=51)

    class DenyRead(FakeCognitive):
        def _authorize(self, action):
            if action == "read_project":
                raise PermissionError("read denied")
            return super()._authorize(action)

    denied = MemoryGraphEngine(DenyRead(store))
    with pytest.raises(PermissionError, match="read denied"):
        denied.expand_chunk_associations([match])


def test_related_event_budget_is_global_across_all_anchors(tmp_path):
    store, cognitive, source, related, imported, chunk, match = _fixture(tmp_path)
    second_source = store.record_event("test.episode", {"observation": "A second linked episode."})
    second_related = store.record_event("test.episode", {"observation": "A second neighbor."})
    cognitive.memory_graph.record_chunk_anchor(source, imported["document_id"], chunk["chunk_index"])
    cognitive.memory_graph.record_chunk_anchor(second_source, imported["document_id"], chunk["chunk_index"])
    cognitive.memory_graph.record_relation(source, "related_to", related)
    cognitive.memory_graph.record_relation(second_source, "related_to", second_related)

    expanded = cognitive.memory_graph.expand_chunk_associations([match], max_related_events=1)

    assert expanded["association_count"] == 2
    assert expanded["related_event_count"] == 1
    assert expanded["related_event_budget"] == 1
    assert expanded["traversal_depth"] == 1


def test_graph_metadata_events_cannot_become_new_source_nodes_or_evidence(tmp_path):
    store, cognitive, source, related, imported, chunk, match = _fixture(tmp_path)
    relation = cognitive.memory_graph.record_relation(source, "related_to", related)
    with pytest.raises(MemoryGraphError, match="evento de origem"):
        cognitive.memory_graph.record_relation(relation["event_id"], "related_to", related)
    with pytest.raises(MemoryGraphError, match="evento de origem"):
        cognitive.memory_graph.record_chunk_anchor(relation["event_id"], imported["document_id"], chunk["chunk_index"])
    with pytest.raises(MemoryGraphError, match="evento de origem"):
        cognitive.memory_graph.record_relation(source, "supports", related, evidence_event_ids=[relation["event_id"]])
    with pytest.raises(MemoryGraphError, match="evento de origem"):
        cognitive.memory_graph.related_events(relation["event_id"])
    with pytest.raises(MemoryGraphError, match="evento de origem"):
        cognitive.memory_graph.list_interpretations(relation["event_id"])
