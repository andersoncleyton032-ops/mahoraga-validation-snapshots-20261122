"""Small deterministic graph algorithms with explicit work budgets.

The helpers are dependency-free so they can run on constrained Python/Android
environments. They analyse caller-supplied graphs only; they do not assign
epistemic status, persist data, or infer causality.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any, Hashable


def bounded_simple_paths(
    adjacency: Mapping[Hashable, list[Mapping[str, Any]]],
    source: Hashable,
    target: Hashable,
    *,
    max_hops: int,
    max_paths: int,
    max_edge_visits: int,
) -> dict[str, Any]:
    """Enumerate shortest-first simple paths under strict work/output caps.

    Each adjacency edge must be a mapping with a hashable target member.
    The function performs breadth-first enumeration, avoids repeated vertices
    within a path, and preserves the caller adjacency ordering. Results contain
    edge mappings from the supplied adjacency without mutating them. The
    truncation flag is conservative when a cap stops exploration while queued
    states remain.
    """
    if not isinstance(adjacency, Mapping):
        raise TypeError("adjacency deve ser um mapeamento.")
    for field, value, minimum, maximum in (
        ("max_hops", max_hops, 1, 32),
        ("max_paths", max_paths, 1, 100),
        ("max_edge_visits", max_edge_visits, 1, 100_000),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not minimum <= value <= maximum
        ):
            raise ValueError(f"{field} deve estar entre {minimum} e {maximum}.")
    if source == target:
        raise ValueError("source e target devem ser diferentes.")

    queue = deque([(source, (source,), ())])
    found: list[tuple[tuple[Hashable, ...], tuple[Mapping[str, Any], ...]]] = []
    edge_visits = 0
    truncated = False

    while queue:
        current, node_path, edge_path = queue.popleft()
        if current == target:
            found.append((node_path, edge_path))
            if len(found) >= max_paths:
                truncated = bool(queue)
                break
            continue
        if len(edge_path) >= max_hops:
            continue

        outgoing = adjacency.get(current, ())
        if not isinstance(outgoing, (list, tuple)):
            continue
        for edge in outgoing:
            if edge_visits >= max_edge_visits:
                truncated = True
                break
            edge_visits += 1
            if not isinstance(edge, Mapping):
                continue
            next_node = edge.get("target")
            if next_node is None:
                continue
            try:
                repeats_node = next_node in node_path
            except TypeError:
                continue
            if repeats_node:
                continue
            queue.append((next_node, node_path + (next_node,), edge_path + (edge,)))
        if truncated:
            break

    return {
        "paths": [
            {"node_ids": list(nodes), "edges": list(edges)}
            for nodes, edges in found
        ],
        "edge_visits": edge_visits,
        "search_may_be_truncated": truncated,
        "max_hops": max_hops,
        "max_paths": max_paths,
        "max_edge_visits": max_edge_visits,
    }
