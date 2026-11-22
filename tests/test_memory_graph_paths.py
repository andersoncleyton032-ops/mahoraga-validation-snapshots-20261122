import pytest

from agent.cognitive_engine import CognitiveEngine
from agent.dharma import Dharma
from agent.knowledge_engine import KnowledgeEngine
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


def _fixture(tmp_path):
    store = KnowledgeStore(tmp_path / "memory-paths.sqlite3")
    graph = MemoryGraphEngine(FakeCognitive(store))
    source = store.record_event("test.episode", {"name": "source"})
    left = store.record_event("test.episode", {"name": "left"})
    right = store.record_event("test.episode", {"name": "right"})
    target = store.record_event("test.episode", {"name": "target"})
    evidence = store.record_event("test.evidence", {"name": "support"})
    return store, graph, source, left, right, target, evidence


def test_trace_paths_returns_shortest_first_candidate_explanations_without_writes(tmp_path):
    store, graph, source, left, right, target, evidence = _fixture(tmp_path)
    graph.record_relation(source, "supports", left, evidence_event_ids=[evidence])
    graph.record_relation(left, "supports", target)
    graph.record_relation(source, "supports", right)
    graph.record_relation(right, "supports", target)
    graph.record_relation(target, "related_to", source)
    before = store.count_events()
    capability = graph.status()
    assert capability["path_tracing_supported"] is True
    assert capability["path_tracing_read_only"] is True
    assert capability["path_tracing_max_hops"] == 6

    result = graph.trace_paths(source, target, max_hops=4)

    assert result["status"] == "completed"
    assert result["path_count"] == 2
    assert [item["node_event_ids"] for item in result["paths"]] == [
        [source, left, target],
        [source, right, target],
    ]
    assert all(item["verified"] is False for item in result["paths"])
    assert all(item["causal_attribution"] == "not_established" for item in result["paths"])
    first_relation = result["paths"][0]["relations"][0]
    assert first_relation["predicate"] == "supports"
    assert first_relation["evidence_event_ids"] == [source, left, evidence]
    assert first_relation["missing_evidence_event_ids"] == []
    assert result["persistent_write_performed"] is False
    assert result["all_paths_unverified"] is True
    assert store.count_events() == before


def test_trace_paths_respects_direction_predicate_and_hop_limit(tmp_path):
    store, graph, source, left, right, target, evidence = _fixture(tmp_path)
    graph.record_relation(source, "supports", left)
    graph.record_relation(left, "supports", target)
    graph.record_relation(source, "blocks", target)

    outgoing = graph.trace_paths(source, target, predicate="supports", max_hops=1)
    assert outgoing["path_count"] == 0

    two_hops = graph.trace_paths(source, target, predicate="supports", max_hops=2)
    assert two_hops["path_count"] == 1
    assert two_hops["paths"][0]["hops"] == 2

    reverse_default = graph.trace_paths(target, source, direction="outgoing")
    reverse_incoming = graph.trace_paths(target, source, direction="incoming", predicate="supports")
    assert reverse_default["path_count"] == 0
    assert reverse_incoming["path_count"] == 1
    assert reverse_incoming["paths"][0]["relations"][0]["traversal_direction"] == "incoming"


def test_trace_paths_rejects_invalid_inputs_and_graph_metadata_endpoints(tmp_path):
    store, graph, source, left, right, target, evidence = _fixture(tmp_path)
    with pytest.raises(MemoryGraphError, match="diferentes"):
        graph.trace_paths(source, source)
    with pytest.raises(MemoryGraphError, match="direction"):
        graph.trace_paths(source, target, direction="sideways")
    with pytest.raises(MemoryGraphError, match="max_hops"):
        graph.trace_paths(source, target, max_hops=True)
    with pytest.raises(MemoryGraphError, match="não existe"):
        graph.trace_paths(source, 999999)

    relation = graph.record_relation(source, "supports", target)
    with pytest.raises(MemoryGraphError, match="eventos de origem"):
        graph.trace_paths(relation["event_id"], target)


def test_trace_paths_requires_read_authorization(tmp_path):
    store, graph, source, left, right, target, evidence = _fixture(tmp_path)
    graph.record_relation(source, "supports", target)

    class DenyRead(FakeCognitive):
        def _authorize(self, action):
            if action == "read_project":
                raise PermissionError("read denied")
            return super()._authorize(action)

    denied = MemoryGraphEngine(DenyRead(store))
    with pytest.raises(PermissionError, match="read denied"):
        denied.trace_paths(source, target)



def test_cognitive_engine_exposes_the_shared_memory_path_api(tmp_path):
    store = KnowledgeStore(tmp_path / "cognitive-memory-paths.sqlite3")
    cognitive = CognitiveEngine(
        store=store,
        knowledge=KnowledgeEngine(store),
        dharma=Dharma(),
    )
    source = store.record_event("test.episode", {"name": "source"})
    target = store.record_event("test.episode", {"name": "target"})
    cognitive.memory_graph.record_relation(source, "related_to", target)

    result = cognitive.trace_memory_paths(source, target)

    assert result["path_count"] == 1
    assert result["paths"][0]["node_event_ids"] == [source, target]
    assert result["persistent_write_performed"] is False
