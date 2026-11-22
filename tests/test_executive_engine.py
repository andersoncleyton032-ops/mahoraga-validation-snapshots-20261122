import pytest
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from agent.dharma import Dharma
from agent.executive_engine import ExecutiveEngine
from agent.memory_graph import MemoryGraphEngine
from agent.store import KnowledgeStore


class FakeCognitive:
    def __init__(self, store):
        self.store = store
        self.dharma = Dharma()


class ProcessInitiativeCognitive(FakeCognitive):
    def review_experiences(self, limit=200):
        return {
            "status": "reviewed",
            "review_complete": True,
            "candidates": [{
                "candidate_id": "a" * 24,
                "task_key": "concurrent adoption",
                "event_ids": [1, 2],
                "episode_count": 2,
                "validated_episode_count": 2,
                "evidence_state": "caller_supplied_not_independently_verified",
            }],
        }

    def review_capabilities(self, persist=False):
        return {"status": "reviewed", "assessment": {"candidate_hypotheses": []}}


def _transition_goal_in_process(db_path, goal_id, barrier):
    store = KnowledgeStore(db_path)
    engine = ExecutiveEngine(FakeCognitive(store))
    barrier.wait(timeout=30)
    try:
        result = engine.transition_goal(goal_id, "active")
        return {"status": result["status"], "goal_status": result["goal"]["status"]}
    except (ValueError, KeyError) as exc:
        return {"status": "rejected", "error": str(exc)}


def _adopt_initiative_in_process(db_path, candidate_id, barrier):
    store = KnowledgeStore(db_path)
    engine = ExecutiveEngine(ProcessInitiativeCognitive(store))
    barrier.wait(timeout=30)
    result = engine.adopt_initiative(candidate_id, approved=True)
    return {
        "status": result["status"],
        "goal_id": result["goal"]["goal_id"],
    }


def _set_focus_in_process(db_path, goal_id, barrier):
    store = KnowledgeStore(db_path)
    engine = ExecutiveEngine(FakeCognitive(store))
    barrier.wait(timeout=30)
    try:
        result = engine.set_focus(goal_id, reason="concurrent focus test")
        return {"status": result["status"], "goal_id": result["goal_id"]}
    except ValueError as exc:
        return {"status": "rejected", "error": str(exc)}


def make_engine(tmp_path):
    store = KnowledgeStore(tmp_path / "executive.sqlite3")
    return ExecutiveEngine(FakeCognitive(store)), store


def test_goal_lifecycle_is_persistent_and_append_only(tmp_path):
    engine, store = make_engine(tmp_path)
    created = engine.create_goal("Consolidar memória", "Melhorar replay e retenção", priority="high")
    goal_id = created["goal"]["goal_id"]

    assert created["goal"]["status"] == "planned"
    assert engine.transition_goal(goal_id, "active")["goal"]["status"] == "active"
    assert engine.set_focus(goal_id)["goal_id"] == goal_id
    assert engine.transition_goal(goal_id, "blocked", note="dependência externa")["goal"]["status"] == "blocked"

    snapshot = engine.snapshot()
    assert snapshot["goal_count"] == 1
    assert snapshot["blocked_count"] == 1
    assert snapshot["focus_goal_id"] is None
    assert len(store.list_events(event_type=engine.GOAL_EVENT)) == 3


def test_goal_transition_rules_reject_invalid_transitions(tmp_path):
    engine, _ = make_engine(tmp_path)
    goal = engine.create_goal("Testar", "Validar transições")["goal"]
    with pytest.raises(ValueError):
        engine.transition_goal(goal["goal_id"], "completed")
    engine.transition_goal(goal["goal_id"], "active")
    engine.transition_goal(goal["goal_id"], "completed")
    with pytest.raises(ValueError):
        engine.transition_goal(goal["goal_id"], "active")


def test_focus_requires_active_goal(tmp_path):
    engine, _ = make_engine(tmp_path)
    goal = engine.create_goal("Foco", "Objetivo para foco")["goal"]
    with pytest.raises(ValueError):
        engine.set_focus(goal["goal_id"])
    engine.transition_goal(goal["goal_id"], "active")
    assert engine.set_focus(goal["goal_id"])["status"] == "focus_updated"


def test_working_memory_context_is_bounded_and_read_only(tmp_path):
    engine, store = make_engine(tmp_path)
    goal = engine.create_goal("Objetivo atual", "Descrição")
    engine.transition_goal(goal["goal"]["goal_id"], "active")
    before = store.counts()
    result = engine.build_context(max_chars=256)
    after = store.counts()
    assert result["status"] == "ready"
    assert result["context_chars"] <= 256
    assert "Objetivo atual" in result["context"]
    assert "\n" in result["context"]
    assert before == after
    assert result["execution_performed"] is False


def test_invalid_goal_input_and_unknown_goal_are_rejected(tmp_path):
    engine, _ = make_engine(tmp_path)
    with pytest.raises(ValueError):
        engine.create_goal("", "Descrição")
    with pytest.raises(KeyError):
        engine.transition_goal("missing", "active")


def test_priority_sorting_and_parent_relationship(tmp_path):
    engine, _ = make_engine(tmp_path)
    parent = engine.create_goal("Projeto", "Objetivo pai", priority="normal")["goal"]
    engine.create_goal("Tarefa secundária", "Subobjetivo", parent_id=parent["goal_id"])
    urgent = engine.create_goal("Incidente", "Prioridade crítica", priority="critical")["goal"]
    snapshot = engine.snapshot()
    assert snapshot["priority_order"][0] == urgent["goal_id"]
    assert snapshot["goal_count"] == 3



def test_goal_inputs_reject_unhashable_types(tmp_path):
    engine, _ = make_engine(tmp_path)
    with pytest.raises(ValueError):
        engine.create_goal("Teste", "Descrição", priority=[])
    with pytest.raises(ValueError):
        engine.create_goal("Teste", "Descrição", parent_id=[])
    goal = engine.create_goal("Teste", "Descrição")["goal"]
    with pytest.raises(ValueError):
        engine.transition_goal(goal["goal_id"], [])
    with pytest.raises(ValueError):
        engine.set_focus([])


def configure_initiative_sources(engine):
    class FakeIntrospection:
        def build_self_model(self, persist=False):
            assert persist is False
            return {
                "open_questions": [
                    "Quais interfaces Android permanecem acessíveis após suspensão?",
                    "Quais interfaces Android permanecem acessíveis após suspensão?",
                ],
            }

    engine.cognitive.introspection = FakeIntrospection()
    engine.cognitive.review_experiences = lambda limit=200: {
        "status": "reviewed",
        "review_complete": True,
        "candidates": [{
            "candidate_id": "a" * 24,
            "task_key": "testar recuperação",
            "event_ids": [11, 12, 13],
            "episode_count": 3,
            "validated_episode_count": 2,
            "evidence_state": "caller_supplied_not_independently_verified",
            "source_independence_verified": False,
        }],
    }
    engine.cognitive.review_capabilities = lambda persist=False: {
        "status": "reviewed",
        "assessment": {
            "candidate_hypotheses": [{
                "tool_id": "command:perfetto",
                "priority": "high",
                "reason": "Ferramenta detectada sem evidência operacional suficiente.",
                "proposed_action": "Criar experimento controlado de leitura do Perfetto.",
                "registered": False,
                "status": "candidate_not_tested",
            }],
        },
    }


def test_initiative_review_synthesizes_existing_sources_without_mutation(tmp_path):
    engine, store = make_engine(tmp_path)
    configure_initiative_sources(engine)
    before = store.counts()

    review = engine.review_initiatives()

    assert review["status"] == "reviewed"
    assert review["candidate_count"] == 3
    assert review["suppressed_duplicate_count"] == 1
    assert {item["kind"] for item in review["candidates"]} == {
        "self_inquiry",
        "experience_pattern",
        "capability_gap",
    }
    inquiry = next(
        item for item in review["candidates"]
        if item["kind"] == "self_inquiry"
    )
    assert inquiry["evidence"]["epistemic_state"] == "open_question_not_conclusion"
    assert review["initiative_policy"]["derived_from_existing_subsystems"] is True
    assert review["initiative_policy"]["automatic_goal_creation"] is False
    assert review["execution_performed"] is False
    assert review["memory_modified"] is False
    assert store.counts() == before


def test_initiative_adoption_requires_approval_and_creates_only_planned_goal(tmp_path):
    engine, store = make_engine(tmp_path)
    configure_initiative_sources(engine)
    candidate = engine.review_initiatives()["candidates"][0]

    with pytest.raises(PermissionError):
        engine.adopt_initiative(candidate["candidate_id"], approved=False)
    assert store.list_events(event_type=engine.GOAL_EVENT) == []

    adopted = engine.adopt_initiative(
        candidate["candidate_id"], approved=True
    )

    assert adopted["status"] == "initiative_adopted_as_planned_goal"
    assert adopted["goal"]["status"] == "planned"
    assert adopted["execution_performed"] is False
    assert adopted["tool_dispatch_performed"] is False
    assert len(store.list_events(event_type=engine.GOAL_EVENT)) == 1

    repeated = engine.adopt_initiative(
        candidate["candidate_id"], approved=True
    )
    assert repeated["status"] == "initiative_already_adopted"
    assert repeated["goal"]["goal_id"] == adopted["goal"]["goal_id"]
    assert len(store.list_events(event_type=engine.GOAL_EVENT)) == 1

    refreshed = engine.review_initiatives()
    assert refreshed["suppressed_adopted_count"] == 1
    assert all(
        item["candidate_id"] != candidate["candidate_id"]
        for item in refreshed["candidates"]
    )


def test_stale_initiative_candidate_cannot_be_adopted(tmp_path):
    engine, store = make_engine(tmp_path)
    configure_initiative_sources(engine)

    with pytest.raises(ValueError):
        engine.adopt_initiative("f" * 24, approved=True)

    assert store.list_events(event_type=engine.GOAL_EVENT) == []


def test_initiative_review_includes_persisted_self_inquiries(tmp_path):
    engine, store = make_engine(tmp_path)
    configure_initiative_sources(engine)
    observation_id = store.record_observation(
        "self_inquiry",
        "O que ainda não foi validado no modo offline?",
        {"status": "open_question"},
        "test",
    )
    counts_before = store.counts()
    events_before = store.list_events(limit=500)

    review = engine.review_initiatives()

    assert store.counts() == counts_before
    assert store.list_events(limit=500) == events_before
    candidate = next(
        item for item in review["candidates"]
        if item["source"] == "persisted_self_inquiry"
    )
    assert candidate["evidence"]["observation_ids"] == [observation_id]
    assert candidate["evidence"]["observation_count"] == 1
    assert candidate["evidence"]["epistemic_state"] == "open_question_not_conclusion"
    assert review["memory_modified"] is False


def test_invalid_self_model_shape_is_reported_unavailable(tmp_path):
    engine, _ = make_engine(tmp_path)
    configure_initiative_sources(engine)
    engine.cognitive.introspection.build_self_model = lambda persist=False: []

    review = engine.review_initiatives()

    assert review["sources"]["operational_self_model"] == "unavailable"
    assert not any(item["kind"] == "self_inquiry" for item in review["candidates"])



def test_research_result_conflicts_become_review_only_initiatives(tmp_path):
    engine, store = make_engine(tmp_path)
    configure_initiative_sources(engine)
    plan_id = "research-" + "a" * 24

    for attempt_id, status in (
        ("initial", "completed"),
        ("rerun-2", "inconclusive"),
        ("rerun-3", "completed"),
    ):
        store.record_event(
            "adaptive.experience.recorded",
            {
                "task": "research initiative self_inquiry",
                "outcome": status,
                "learning_state": "episodic_only",
                "validated": False,
                "references": {
                    "research_plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "result_status": status,
                    "reported_by": "caller_supplied_not_independently_verified",
                    "evidence_refs": [f"ci://{attempt_id}"],
                },
            },
        )

    counts_before = store.counts()
    events_before = store.list_events(limit=500)

    review = engine.review_initiatives()

    assert store.counts() == counts_before
    assert store.list_events(limit=500) == events_before
    assert review["research_result_history"]["status"] == "reviewed"
    assert review["research_result_history"]["mixed_plan_count"] == 1
    assert review["research_result_history"]["automatic_conflict_resolution"] is False

    candidate = next(
        item for item in review["candidates"]
        if item["kind"] == "research_result_conflict"
    )
    assert candidate["source"] == "research_result_feedback"
    assert len(
        f"initiative_candidate:{candidate['candidate_id']}"
    ) <= 60
    assert candidate["status"] == "candidate_requires_human_review"
    assert candidate["execution_performed"] is False
    assert candidate["evidence"]["research_plan_id"] == plan_id
    assert candidate["evidence"]["result_status_counts"] == {
        "completed": 2,
        "inconclusive": 1,
    }
    assert candidate["evidence"]["source_independence_verified"] is False
    assert candidate["evidence"]["epistemic_state"] == (
        "caller_reported_status_conflict_requires_review"
    )
    assert review["initiative_policy"]["automatic_result_truth_selection"] is False
    assert review["initiative_policy"]["automatic_conflict_resolution"] is False

    with pytest.raises(PermissionError):
        engine.adopt_initiative(candidate["candidate_id"], approved=False)
    adopted = engine.adopt_initiative(
        candidate["candidate_id"], approved=True
    )
    assert adopted["status"] == "initiative_adopted_as_planned_goal"
    assert adopted["goal"]["status"] == "planned"
    assert adopted["execution_performed"] is False

    refreshed = engine.review_initiatives()
    assert refreshed["suppressed_adopted_count"] == 1
    assert all(
        item["candidate_id"] != candidate["candidate_id"]
        for item in refreshed["candidates"]
    )


def test_single_status_research_history_does_not_create_conflict_candidate(tmp_path):
    engine, store = make_engine(tmp_path)
    configure_initiative_sources(engine)
    plan_id = "research-" + "b" * 24
    for attempt_id in ("initial", "rerun-2"):
        store.record_event(
            "adaptive.experience.recorded",
            {
                "task": "research initiative self_inquiry",
                "outcome": "completed",
                "references": {
                    "research_plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "result_status": "completed",
                    "reported_by": "caller_supplied_not_independently_verified",
                },
            },
        )

    review = engine.review_initiatives()

    assert review["research_result_history"]["mixed_plan_count"] == 0
    assert not any(
        item["kind"] == "research_result_conflict"
        for item in review["candidates"]
    )
    assert review["memory_modified"] is False



def test_malformed_research_result_status_is_ignored_safely(tmp_path):
    engine, store = make_engine(tmp_path)
    configure_initiative_sources(engine)
    store.record_event(
        "adaptive.experience.recorded",
        {
            "references": {
                "research_plan_id": "research-" + "c" * 24,
                "result_status": ["completed"],
                "reported_by": "caller_supplied_not_independently_verified",
            },
        },
    )

    review = engine.review_initiatives()

    assert review["status"] == "reviewed"
    assert review["research_result_history"]["mixed_plan_count"] == 0
    assert not any(
        item["kind"] == "research_result_conflict"
        for item in review["candidates"]
    )


def test_same_goal_transition_is_idempotent_across_processes(tmp_path):
    db_path = tmp_path / "executive-transition-process.sqlite3"
    store = KnowledgeStore(db_path)
    engine = ExecutiveEngine(FakeCognitive(store))
    goal = engine.create_goal("Concorrência", "Uma única transição")["goal"]
    context = get_context("spawn")
    with context.Manager() as manager:
        barrier = manager.Barrier(2)
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
            futures = [
                executor.submit(
                    _transition_goal_in_process,
                    str(db_path),
                    goal["goal_id"],
                    barrier,
                )
                for _ in range(2)
            ]
            results = [future.result(timeout=45) for future in futures]

    assert sum(item["status"] == "updated" for item in results) == 1
    assert sum(item["status"] == "rejected" for item in results) == 1
    goal_events = store.list_events(limit=20, event_type=engine.GOAL_EVENT)
    assert len(goal_events) == 2
    assert engine.snapshot()["active_count"] == 1


def test_initiative_adoption_is_unique_across_processes(tmp_path):
    db_path = tmp_path / "executive-adoption-process.sqlite3"
    store = KnowledgeStore(db_path)
    context = get_context("spawn")
    candidate_id = "experience:" + "a" * 24

    with context.Manager() as manager:
        barrier = manager.Barrier(2)
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
            futures = [
                executor.submit(
                    _adopt_initiative_in_process,
                    str(db_path),
                    candidate_id,
                    barrier,
                )
                for _ in range(2)
            ]
            results = [future.result(timeout=45) for future in futures]

    assert len({item["goal_id"] for item in results}) == 1
    assert sorted(item["status"] for item in results) == [
        "initiative_adopted_as_planned_goal",
        "initiative_already_adopted",
    ]
    events = store.list_events(limit=20, event_type=ExecutiveEngine.GOAL_EVENT)
    assert len(events) == 1


def test_focus_update_is_compare_and_swap_across_processes(tmp_path):
    db_path = tmp_path / "executive-focus-process.sqlite3"
    store = KnowledgeStore(db_path)
    engine = ExecutiveEngine(FakeCognitive(store))
    first = engine.create_goal("Foco A", "Primeira meta")["goal"]
    second = engine.create_goal("Foco B", "Segunda meta")["goal"]
    engine.transition_goal(first["goal_id"], "active")
    engine.transition_goal(second["goal_id"], "active")

    context = get_context("spawn")
    with context.Manager() as manager:
        barrier = manager.Barrier(2)
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
            futures = [
                executor.submit(
                    _set_focus_in_process,
                    str(db_path),
                    goal_id,
                    barrier,
                )
                for goal_id in (first["goal_id"], second["goal_id"])
            ]
            results = [future.result(timeout=45) for future in futures]

    assert sum(item["status"] == "focus_updated" for item in results) == 1
    assert sum(item["status"] == "rejected" for item in results) == 1
    focus_events = store.list_events(
        limit=20, event_type=engine.FOCUS_EVENT
    )
    assert len(focus_events) == 1
    assert engine.snapshot()["focus_goal_id"] in {
        first["goal_id"],
        second["goal_id"],
    }


def test_concurrent_goal_transition_is_serialized_on_shared_instance(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from time import sleep

    engine, store = make_engine(tmp_path)
    goal = engine.create_goal("Meta concorrente", "Validar transição única")["goal"]
    goal_id = goal["goal_id"]
    original_record_event_once = store.record_event_once
    workers = 12
    barrier = Barrier(workers)

    def delayed_record_event_once(event_type, idempotency_key, payload=None, severity="info"):
        if event_type == engine.GOAL_EVENT:
            snapshot = payload.get("goal", {}) if isinstance(payload, dict) else {}
            history = snapshot.get("history", [])
            if history and history[-1].get("status") == "active":
                sleep(0.02)
        return original_record_event_once(event_type, idempotency_key, payload, severity)

    store.record_event_once = delayed_record_event_once

    def transition():
        barrier.wait(timeout=5)
        try:
            result = engine.transition_goal(goal_id, "active")
            return {"status": "updated", "goal": result["goal"]}
        except ValueError as exc:
            return {"status": "rejected", "reason": str(exc)}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda _: transition(), range(workers)))

    assert sum(item["status"] == "updated" for item in results) == 1
    assert sum(item["status"] == "rejected" for item in results) == workers - 1
    snapshot = engine.snapshot()
    persisted = store.list_events(event_type=engine.GOAL_EVENT, limit=100)
    assert snapshot["goal_count"] == 1
    assert snapshot["active_count"] == 1
    assert len(persisted) == 2
    final_history = snapshot["goals_by_status"]["active"][0]["history"]
    assert [item["status"] for item in final_history] == ["planned", "active"]


def test_executive_read_methods_remain_reentrant_under_initiative_review(tmp_path):
    engine, _ = make_engine(tmp_path)

    class FakeIntrospection:
        def build_self_model(self, persist=False):
            assert persist is False
            return {"open_questions": ["Como validar continuidade executiva?"]}

    engine.cognitive.introspection = FakeIntrospection()
    engine.cognitive.review_experiences = lambda limit=200: {
        "status": "reviewed", "review_complete": True, "candidates": []
    }
    engine.cognitive.review_capabilities = lambda persist=False: {
        "status": "reviewed", "assessment": {"candidate_hypotheses": []}
    }

    review = engine.review_initiatives()
    snapshot = engine.snapshot()
    context = engine.build_context()
    status = engine.status()

    assert review["candidate_count"] == 1
    assert snapshot["goal_count"] == 0
    assert context["status"] == "ready"
    assert status["goal_count"] == 0


class FakeMemoryGraph:
    def __init__(self, relations_by_event=None):
        self.relations_by_event = relations_by_event or {}
        self.scan_limits = []

    def list_relations(self, *, event_id, limit=200):
        self.scan_limits.append(limit)
        records = self.relations_by_event.get(event_id, [])[:limit]
        all_records = self.relations_by_event.get(event_id, [])
        return {
            "status": "completed",
            "records": records,
            "count": len(records),
            "history_window_limit": limit,
            "history_may_be_incomplete": len(all_records) > limit,
        }


def _goal_event_id(store, goal_id):
    for event in store.list_events(limit=100, event_type=ExecutiveEngine.GOAL_EVENT):
        payload = event.get("payload", {})
        goal = payload.get("goal") if isinstance(payload, dict) else None
        if isinstance(goal, dict) and goal.get("goal_id") == goal_id:
            return event["id"]
    raise AssertionError(f"Evento do objetivo {goal_id} não encontrado")


def test_goal_transition_review_replays_only_explicit_unverified_associations(tmp_path):
    engine, store = make_engine(tmp_path)
    previous = engine.create_goal("Objetivo anterior", "Primeira direção")["goal"]
    next_goal = engine.create_goal("Novo objetivo", "Direção seguinte")["goal"]
    episode_id = store.record_event(
        "learning_episode",
        {"kind": "test_fixture", "description": "Experiência associada às duas metas"},
        severity="info",
    )
    previous_event_id = _goal_event_id(store, previous["goal_id"])
    next_event_id = _goal_event_id(store, next_goal["goal_id"])
    graph = FakeMemoryGraph({
        previous_event_id: [{
            "event_id": 90001,
            "subject_event_id": previous_event_id,
            "object_event_id": episode_id,
            "predicate": "contextual_candidate",
            "epistemic_state": "candidate_unverified",
            "verified": False,
        }],
        next_event_id: [{
            "event_id": 90002,
            "subject_event_id": episode_id,
            "object_event_id": next_event_id,
            "predicate": "contextual_candidate",
            "epistemic_state": "candidate_unverified",
            "verified": False,
        }],
    })
    engine.cognitive.memory_graph = graph
    counts_before = store.counts()
    events_before = store.list_events(limit=1000)

    review = engine.review_goal_transition(
        previous["goal_id"], next_goal["goal_id"]
    )

    assert review["status"] == "reviewed"
    assert review["shared_candidate_event_ids"] == [episode_id]
    assert review["shared_candidate_event_count"] == 1
    assert review["candidate_link_count"] == 2
    assert all(item["epistemic_state"] == "candidate_unverified"
               for item in review["candidate_links"])
    assert all(item["verified"] is False for item in review["candidate_links"])
    assert review["memory_modified"] is False
    assert review["goal_state_modified"] is False
    assert review["automatic_learning_consolidation"] is False
    assert review["automatic_tool_dispatch"] is False
    assert review["execution_performed"] is False
    assert store.counts() == counts_before
    assert store.list_events(limit=1000) == events_before


def test_goal_transition_review_reports_missing_memory_graph_without_mutation(tmp_path):
    engine, store = make_engine(tmp_path)
    previous = engine.create_goal("Objetivo anterior", "Primeira direção")["goal"]
    next_goal = engine.create_goal("Novo objetivo", "Direção seguinte")["goal"]
    counts_before = store.counts()
    events_before = store.list_events(limit=1000)

    review = engine.review_goal_transition(previous["goal_id"], next_goal["goal_id"])

    assert review["status"] == "memory_graph_unavailable"
    assert review["candidate_links"] == []
    assert review["memory_modified"] is False
    assert store.counts() == counts_before
    assert store.list_events(limit=1000) == events_before


def test_goal_transition_review_bounds_total_graph_scan_and_validates_inputs(tmp_path):
    engine, store = make_engine(tmp_path)
    previous = engine.create_goal("Objetivo anterior", "Primeira direção")["goal"]
    next_goal = engine.create_goal("Novo objetivo", "Direção seguinte")["goal"]
    engine.transition_goal(previous["goal_id"], "active")
    engine.transition_goal(next_goal["goal_id"], "active")
    previous_event_id = _goal_event_id(store, previous["goal_id"])
    next_event_id = _goal_event_id(store, next_goal["goal_id"])
    graph = FakeMemoryGraph()
    engine.cognitive.memory_graph = graph

    review = engine.review_goal_transition(
        previous["goal_id"],
        next_goal["goal_id"],
        relation_limit=37,
        snapshots_per_goal=2,
    )

    assert review["status"] == "reviewed"
    assert review["goal_event_snapshot_count"] == {"previous": 2, "next": 2}
    assert len(graph.scan_limits) == 4
    assert sum(graph.scan_limits) == 37
    assert all(1 <= value <= 37 for value in graph.scan_limits)
    with pytest.raises(ValueError):
        engine.review_goal_transition(previous["goal_id"], next_goal["goal_id"], relation_limit=0)
    with pytest.raises(ValueError):
        engine.review_goal_transition(previous["goal_id"], next_goal["goal_id"], snapshots_per_goal=11)
    with pytest.raises(ValueError):
        engine.review_goal_transition(previous["goal_id"], previous["goal_id"])
    with pytest.raises(KeyError):
        engine.review_goal_transition("missing", next_goal["goal_id"])
    assert previous_event_id > 0 and next_event_id > 0


def test_goal_transition_review_uses_real_memory_graph_without_mutation(tmp_path):
    engine, store = make_engine(tmp_path)
    previous = engine.create_goal("Objetivo anterior", "Contexto anterior")["goal"]
    next_goal = engine.create_goal("Novo objetivo", "Contexto seguinte")["goal"]
    episode = store.record_observation_and_event(
        "learning_episode",
        "Episódio explicitamente ligado aos dois objetivos",
        {"kind": "integration_fixture"},
        "test",
        "learning_episode.recorded",
        {"fixture": "goal_transition_review"},
    )
    episode_id = episode["event_id"]
    previous_event_id = _goal_event_id(store, previous["goal_id"])
    next_event_id = _goal_event_id(store, next_goal["goal_id"])

    def authorize(action, target=""):
        decision = engine.dharma.evaluate(action, target=target)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        return decision

    engine.cognitive._authorize = authorize
    graph = MemoryGraphEngine(engine.cognitive)
    engine.cognitive.memory_graph = graph
    graph.record_relation(
        previous_event_id,
        "contextual_candidate",
        episode_id,
        context={"test_fixture": True},
    )
    graph.record_relation(
        episode_id,
        "contextual_candidate",
        next_event_id,
        context={"test_fixture": True},
    )
    before_counts = store.counts()
    before_events = store.list_events(limit=1000)

    review = engine.review_goal_transition(
        previous["goal_id"], next_goal["goal_id"]
    )

    assert review["status"] == "reviewed"
    assert review["shared_candidate_event_ids"] == [episode_id]
    assert review["candidate_link_count"] == 2
    assert all(
        item["epistemic_state"] == "candidate_unverified"
        and item["verified"] is False
        for item in review["candidate_links"]
    )
    assert store.counts() == before_counts
    assert store.list_events(limit=1000) == before_events
    assert review["memory_modified"] is False
    assert review["goal_state_modified"] is False
    assert review["automatic_learning_consolidation"] is False
    assert review["automatic_tool_dispatch"] is False

class IncompleteReplayInitiativeCognitive(ProcessInitiativeCognitive):
    def review_experiences(self, limit=200):
        return {
            "status": "reviewed",
            "review_complete": False,
            "window_truncated": True,
            "events_examined": limit,
            "total_recorded_episodes": limit + 1,
            "candidates": [{
                "candidate_id": "b" * 24,
                "task_key": "partial replay pattern",
                "event_ids": [1, 2, 3],
                "episode_count": 3,
                "validated_episode_count": 3,
                "evidence_state": "independently_verified_by_configured_verifier",
            }],
        }


def test_incomplete_experience_replay_is_not_promoted_to_initiative(
    tmp_path,
):
    store = KnowledgeStore(tmp_path / "incomplete-replay.sqlite3")
    engine = ExecutiveEngine(IncompleteReplayInitiativeCognitive(store))

    result = engine.review_initiatives()

    assert result["candidate_count"] == 0
    assert result["experience_replay_history"]["status"] == "incomplete"
    assert result["experience_replay_history"]["window_truncated"] is True
    assert result["experience_replay_history"]["candidate_proposals_suppressed"] is True
    assert result["sources"]["experience_replay"] == "reviewed_history_incomplete"

