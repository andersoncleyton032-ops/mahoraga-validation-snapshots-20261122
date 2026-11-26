import pytest

from agent.graph_algorithms import bounded_simple_paths


def test_bounded_paths_returns_shortest_first_and_avoids_cycles():
    adjacency = {
        1: [{"target": 2, "edge": "a"}, {"target": 3, "edge": "b"}],
        2: [{"target": 4, "edge": "c"}],
        3: [{"target": 4, "edge": "d"}],
        4: [{"target": 1, "edge": "cycle"}],
    }

    result = bounded_simple_paths(
        adjacency, 1, 4, max_hops=3, max_paths=10, max_edge_visits=20
    )

    assert [path["node_ids"] for path in result["paths"]] == [
        [1, 2, 4],
        [1, 3, 4],
    ]
    assert result["search_may_be_truncated"] is False
    assert result["edge_visits"] == 4


def test_bounded_paths_reports_output_and_work_truncation():
    adjacency = {
        "s": [{"target": "a"}, {"target": "b"}],
        "a": [{"target": "t"}],
        "b": [{"target": "t"}],
    }

    limited_paths = bounded_simple_paths(
        adjacency, "s", "t", max_hops=3, max_paths=1, max_edge_visits=10
    )
    assert len(limited_paths["paths"]) == 1
    assert limited_paths["search_may_be_truncated"] is True

    limited_work = bounded_simple_paths(
        adjacency, "s", "t", max_hops=3, max_paths=10, max_edge_visits=1
    )
    assert limited_work["edge_visits"] == 1
    assert limited_work["search_may_be_truncated"] is True


def test_bounded_paths_enforces_limits_and_distinct_endpoints():
    with pytest.raises(ValueError, match="max_hops"):
        bounded_simple_paths({}, 1, 2, max_hops=True, max_paths=1, max_edge_visits=1)
    with pytest.raises(ValueError, match="diferentes"):
        bounded_simple_paths({}, 1, 1, max_hops=1, max_paths=1, max_edge_visits=1)
    with pytest.raises(TypeError):
        bounded_simple_paths([], 1, 2, max_hops=1, max_paths=1, max_edge_visits=1)
