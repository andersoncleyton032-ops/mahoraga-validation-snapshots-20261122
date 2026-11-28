"""Curated snapshot for atomic goal-capacity concurrency validation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from agent.executive_engine import ExecutiveEngine
from agent.store import KnowledgeStore


class _AllowDharma:
    def evaluate(self, action):
        return SimpleNamespace(allowed=True, reason="")


class _EmptyMemoryGraph:
    GRAPH_EVENT_TYPES = ()

    def list_relations(self, *, event_id, limit):
        return {
            "records": [],
            "history_may_be_incomplete": False,
            "history_window_limit": limit,
        }


class _CognitiveStub:
    def __init__(self, store):
        self.store = store
        self.dharma = _AllowDharma()
        self.memory_graph = _EmptyMemoryGraph()


def _engine(tmp_path):
    store = KnowledgeStore(tmp_path / "executive-projection.sqlite3")
    return ExecutiveEngine(_CognitiveStub(store)), store


def _record_goal(store, goal_id, revision, status="planned"):
    return store.record_event(
        ExecutiveEngine.GOAL_EVENT,
        {
            "goal": {
                "goal_id": goal_id,
                "revision": revision,
                "status": status,
            }
        },
    )


def test_goal_projection_survives_more_than_1000_snapshots(tmp_path):
    engine, store = _engine(tmp_path)
    for revision in range(1205):
        _record_goal(store, "goal-primary", revision, "active")
    _record_goal(store, "goal-older", 0, "planned")

    goals = engine._goals()

    assert set(goals) == {"goal-primary", "goal-older"}
    assert goals["goal-primary"]["revision"] == 1204
    assert goals["goal-primary"]["status"] == "active"
    assert goals["goal-older"]["revision"] == 0


def test_goal_projection_preserves_max_goals_after_event_churn(tmp_path):
    engine, store = _engine(tmp_path)
    for goal_index in range(engine.MAX_GOALS):
        goal_id = f"goal-{goal_index:03d}"
        for revision in range(6):
            _record_goal(store, goal_id, revision)

    assert len(engine._goals()) == engine.MAX_GOALS
    with pytest.raises(ValueError, match="Limite de objetivos"):
        engine.create_goal("extra", "must not bypass the historical goal limit")


def test_goal_projection_fails_closed_if_store_exceeds_max_goals(tmp_path):
    engine, store = _engine(tmp_path)
    for goal_index in range(engine.MAX_GOALS + 1):
        _record_goal(store, f"overflow-{goal_index:03d}", 0)

    with pytest.raises(RuntimeError, match="MAX_GOALS"):
        engine._goals()


def test_goal_history_query_ignores_unrelated_global_event_volume(tmp_path):
    engine, store = _engine(tmp_path)
    old_event_id = _record_goal(store, "goal-old", 0)
    for index in range(1200):
        store.record_event("unrelated.event", {"sequence": index})

    events = store.list_goal_events(
        ExecutiveEngine.GOAL_EVENT,
        "goal-old",
        limit=10,
    )

    assert [event["id"] for event in events] == [old_event_id]


def test_goal_transition_review_uses_per_goal_history_after_1000_events(tmp_path):
    engine, store = _engine(tmp_path)
    for revision in range(600):
        _record_goal(store, "goal-previous", revision, "completed")
        _record_goal(store, "goal-next", revision, "active")

    review = engine.review_goal_transition(
        "goal-previous",
        "goal-next",
        relation_limit=10,
        snapshots_per_goal=3,
    )

    assert review["status"] == "reviewed"
    assert review["goal_event_snapshot_count"] == {"previous": 3, "next": 3}
    assert review["history_scope"] == "per_goal_id"
    assert review["history_window_limit"] == 3
    assert review["history_may_be_incomplete"] is True
    assert review["execution_performed"] is False
    assert review["memory_modified"] is False


def test_concurrent_goal_creation_cannot_exceed_global_capacity(tmp_path):
    database = tmp_path / "executive-projection.sqlite3"
    store = KnowledgeStore(database)
    for index in range(ExecutiveEngine.MAX_GOALS - 1):
        _record_goal(store, f"existing-{index:03d}", 0)

    engines = [
        ExecutiveEngine(_CognitiveStub(KnowledgeStore(database))),
        ExecutiveEngine(_CognitiveStub(KnowledgeStore(database))),
    ]
    both_read_capacity = Barrier(2)
    for engine in engines:
        original_goals = engine._goals

        def gated_goals(original=original_goals):
            snapshot = original()
            both_read_capacity.wait(timeout=10)
            return snapshot

        engine._goals = gated_goals

    def create(engine, title):
        try:
            engine.create_goal(title, "concurrent capacity check")
            return "created"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda item: create(*item),
            zip(engines, ("last-slot-a", "last-slot-b")),
        ))

    assert results.count("created") == 1
    assert sum("Limite de objetivos" in result for result in results) == 1
    final_engine = ExecutiveEngine(_CognitiveStub(KnowledgeStore(database)))
    assert len(final_engine._goals()) == ExecutiveEngine.MAX_GOALS

