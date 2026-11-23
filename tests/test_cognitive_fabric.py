import pytest

from agent.cognitive_fabric import (
    CognitiveFabric,
    CognitiveFabricError,
    CognitiveFabricLimitError,
    SignalDraft,
)
from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore


def test_fabric_dispatches_causally_related_signals_and_tracks_flows():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["input", "language", "knowledge", "reasoning"],
        verified_relationships={
            "language_uses_input": ("language", "input"),
            "knowledge_uses_language": ("knowledge", "language"),
        },
    )
    workspace = fabric.new_workspace(metadata={"kind": "unit_test"})
    workspace.put("request", {"text": "hello"}, source="input")

    def language_handler(signal, current):
        assert current.get("request") == {"text": "hello"}
        return SignalDraft(
            topic="language.ready",
            source="language",
            target="knowledge",
            payload={"intent": "greeting"},
        )

    def knowledge_handler(signal, current):
        assert signal.causation_id
        return SignalDraft(
            topic="knowledge.ready",
            source="knowledge",
            target="reasoning",
            payload={"references": 1},
        )

    def reasoning_handler(signal, current):
        assert signal.target == "reasoning"
        return None

    fabric.subscribe("request.received", "language", language_handler)
    fabric.subscribe("language.ready", "knowledge", knowledge_handler)
    fabric.subscribe("knowledge.ready", "reasoning", reasoning_handler)
    first = fabric.publish(
        workspace,
        SignalDraft(
            topic="request.received",
            source="input",
            target="language",
            payload={"character_count": 5},
        ),
    )

    assert first.topic == "request.received"
    with pytest.raises(TypeError):
        first.payload["character_count"] = 99
    assert first.as_dict()["payload"]["character_count"] == 5
    assert [item.topic for item in workspace.signals] == [
        "request.received",
        "language.ready",
        "knowledge.ready",
    ]
    assert workspace.signals[1].causation_id == workspace.signals[0].signal_id
    assert workspace.signals[2].causation_id == workspace.signals[1].signal_id
    snapshot = fabric.connectome_snapshot()
    assert snapshot["node_count"] == 4
    assert snapshot["verified_edge_count"] == 2
    assert snapshot["observed_flow_count"] == 3
    assert all(item["observed_count"] == 1 for item in snapshot["observed_runtime_flows"])


def test_fabric_rejects_unverified_or_unknown_connectome_edges():
    fabric = CognitiveFabric()
    with pytest.raises(CognitiveFabricError):
        fabric.configure_connectome(
            component_ids=["cognitive", "store"],
            verified_relationships={"invalid": ("cognitive", "missing")},
        )


def test_undelivered_signal_is_not_counted_as_a_runtime_flow():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["source", "target"],
        verified_relationships={"source_target": ("source", "target")},
    )
    workspace = fabric.new_workspace()
    fabric.publish(
        workspace,
        SignalDraft(
            topic="no.subscriber",
            source="source",
            target="target",
            payload={},
        ),
    )
    assert fabric.connectome_snapshot()["observed_flow_count"] == 0


def test_workspace_is_transient_bounded_and_strict_json():
    fabric = CognitiveFabric()
    fabric.configure_connectome(component_ids=["core"], verified_relationships={})
    workspace = fabric.new_workspace()
    workspace.put("state", {"ok": True}, source="core")
    assert workspace.get("state") == {"ok": True}

    with pytest.raises(CognitiveFabricError):
        workspace.put("nan", {"value": float("nan")}, source="core")
    with pytest.raises(CognitiveFabricError):
        workspace.put("object", {"value": object()}, source="core")
    with pytest.raises(CognitiveFabricError):
        fabric.publish(
            workspace,
            SignalDraft(
                topic="bad.signal",
                source="unknown_component",
                payload={},
            ),
        )


def test_fabric_limits_signal_dispatch_depth():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["a", "b"],
        verified_relationships={"a_b": ("a", "b")},
    )

    def loop_handler(signal, workspace):
        return SignalDraft(
            topic="loop",
            source="b",
            target="a",
            payload={"next": True},
        )

    fabric.subscribe("loop", "a", loop_handler)
    fabric.subscribe("loop", "b", loop_handler)
    workspace = fabric.new_workspace()
    with pytest.raises(CognitiveFabricLimitError):
        fabric.publish(
            workspace,
            SignalDraft(topic="loop", source="a", target="b", payload={}),
        )
    assert len(workspace.signals) <= fabric.MAX_SIGNALS_PER_CYCLE


class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


def test_integrated_core_uses_one_bounded_cognitive_signal_cycle(tmp_path):
    store = KnowledgeStore(tmp_path / "fabric.sqlite3")
    core = IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=FakeHardware(),
    )
    before_counts = store.counts()
    before_events = store.list_events(limit=500)

    result = core.prepare_request(
        "Como o contexto é integrado?",
        include_capability_review=False,
    )

    trace = result["cognitive_fabric"]
    topics = [item["topic"] for item in trace["signals"]]
    assert topics == [
        "request.received",
        "language.completed",
        "knowledge.retrieved",
        "reasoning.completed",
        "executive.context_ready",
        "conversation.context_ready",
        "introspection.context_ready",
        "context.ready",
    ]
    assert trace["signal_count"] == 8
    assert trace["effectome"]["causal_attribution"] == "not_established"
    assert len(trace["stage_measurements"]) >= 6
    assert trace["persistent_memory_written"] is False
    assert trace["background_work_started"] is False
    assert result["side_effects"]["memory_modified"] is False
    assert result["side_effects"]["tools_executed"] is False
    assert result["memory_graph"]["new_database_or_tables"] is False
    assert result["memory_graph"]["semantic_promotion_automatic"] is False
    assert store.counts() == before_counts
    assert store.list_events(limit=500) == before_events

    connectome = core.inspect_cognitive_fabric()
    assert connectome["node_count"] >= 20
    assert "memory_graph" in connectome["nodes"]
    assert any(
        edge["relationship_id"] == "introspection_memory_graph"
        for edge in connectome["verified_structural_edges"]
    )
    assert connectome["verified_edge_count"] >= 30
    assert connectome["observed_flow_count"] == 8
    assert connectome["persistence"] == "in_memory_only"



def test_connectome_flow_counters_and_snapshots_are_thread_safe():
    from concurrent.futures import ThreadPoolExecutor

    source_ids = [f"source_{index}" for index in range(100)]
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=source_ids + ["target"],
        verified_relationships={},
    )
    fabric.subscribe("sample.delivered", "target", lambda signal, workspace: None)

    def publish(index):
        source = source_ids[index % len(source_ids)]
        workspace = fabric.new_workspace()
        fabric.publish(
            workspace,
            SignalDraft(
                topic="sample.delivered",
                source=source,
                target="target",
                payload={"index": index},
            ),
        )
        snapshot = fabric.connectome_snapshot()
        assert snapshot["observed_flow_count"] <= len(source_ids)

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(publish, range(800)))

    snapshot = fabric.connectome_snapshot()
    assert snapshot["observed_flow_count"] == len(source_ids)
    assert sum(item["observed_count"] for item in snapshot["observed_runtime_flows"]) == 800
    assert all(item["causal_attribution"] == "not_established"
               for item in snapshot["observed_runtime_flows"])
