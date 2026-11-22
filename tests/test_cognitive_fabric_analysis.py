import pytest

from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore
from agent.cognitive_fabric import (
    CognitiveFabric,
    CognitiveFabricError,
    SignalDraft,
)


def test_analyze_connectome_separates_verified_structure_from_observed_paths():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["a", "b", "c", "isolated"],
        verified_relationships={
            "a_b": ("a", "b"),
            "b_c": ("b", "c"),
            "b_a": ("b", "a"),
        },
    )
    fabric.subscribe("first", "b", lambda signal, workspace: None)
    fabric.subscribe("second", "c", lambda signal, workspace: None)

    first_workspace = fabric.new_workspace()
    fabric.publish(
        first_workspace,
        SignalDraft(topic="first", source="a", target="b", payload={}),
    )
    second_workspace = fabric.new_workspace()
    fabric.publish(
        second_workspace,
        SignalDraft(topic="second", source="b", target="c", payload={}),
    )

    result = fabric.analyze_connectome("a", "c")

    assert result["schema"] == "mahoraga.connectome_analysis"
    assert result["structural"]["edge_count"] == 3
    assert result["structural"]["edge_count_basis"] == "unique_ordered_component_pairs"
    assert result["structural"]["reciprocal_pair_count"] == 1
    assert result["structural"]["isolated_components"] == ["isolated"]
    assert result["structural_paths"]["path_count"] == 1
    assert result["structural_paths"]["paths"][0]["component_ids"] == ["a", "b", "c"]
    assert result["structural_paths"]["paths"][0]["edges"][0]["source"] == "a"
    assert result["structural_paths"]["paths"][0]["edges"][0]["target_component"] == "b"
    assert result["observed_runtime"]["edge_count"] == 2
    assert result["observed_runtime"]["total_deliveries"] == 2
    assert result["observed_runtime_paths"]["path_count"] == 1
    assert result["observed_runtime_paths"]["paths"][0]["component_ids"] == ["a", "b", "c"]
    assert result["observed_runtime_paths"]["paths"][0]["chain_capability_proven"] is False
    assert result["causal_attribution"] == "not_established"
    assert result["persistent_memory_written"] is False
    assert result["execution_performed"] is False


def test_analyze_connectome_without_path_query_still_returns_topology_metrics():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["one", "two"],
        verified_relationships={"one_two": ("one", "two")},
    )

    result = fabric.analyze_connectome()

    assert result["structural"]["source_components"] == ["one"]
    assert result["structural"]["sink_components"] == ["two"]
    assert result["path_query"] is None
    assert result["structural_paths"] is None
    assert result["observed_runtime_paths"] is None


def test_analyze_connectome_validates_query_and_work_budgets():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["one", "two"],
        verified_relationships={"one_two": ("one", "two")},
    )

    with pytest.raises(CognitiveFabricError, match="juntos"):
        fabric.analyze_connectome("one")
    with pytest.raises(CognitiveFabricError, match="existir"):
        fabric.analyze_connectome("one", "missing")
    with pytest.raises(CognitiveFabricError, match="max_paths"):
        fabric.analyze_connectome("one", "two", max_paths=0)



class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


def test_integrated_core_exposes_fabric_analysis(tmp_path):
    core = IntegratedCore(
        root=tmp_path,
        store=KnowledgeStore(tmp_path / "integrated-fabric-analysis.sqlite3"),
        hardware=FakeHardware(),
    )

    result = core.analyze_cognitive_fabric()

    assert result["schema"] == "mahoraga.connectome_analysis"
    assert result["node_count"] >= 20
    assert result["persistent_memory_written"] is False
    assert result["execution_performed"] is False
