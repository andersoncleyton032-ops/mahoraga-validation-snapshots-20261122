"""Persistent executive control and bounded working-memory state.

Goals are append-only records. This module plans and tracks work; it never
dispatches tools, executes commands or changes project files.
"""
from __future__ import annotations

import re

import uuid
from datetime import datetime, timezone
from functools import wraps
from threading import RLock
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _synchronized(method):
    """Serialize read-modify-write operations on one shared executive instance."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return wrapper


class ExecutiveEngine:
    VERSION = "0.1.0"
    GOAL_EVENT = "executive.goal.snapshot"
    FOCUS_EVENT = "executive.focus.changed"
    MAX_GOALS = 200
    MAX_HISTORY = 30
    PRIORITIES = {"low": 1, "normal": 2, "high": 3, "critical": 4}
    TRANSITIONS = {
        "planned": {"active", "cancelled"},
        "active": {"blocked", "suspended", "completed", "cancelled"},
        "blocked": {"active", "suspended", "cancelled"},
        "suspended": {"active", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }

    def __init__(self, cognitive):
        self.cognitive = cognitive
        self.store = cognitive.store
        self.dharma = cognitive.dharma
        self._state_lock = RLock()

    def _authorize(self, action: str) -> None:
        decision = self.dharma.evaluate(action)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    @staticmethod
    def _text(value: Any, field: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"{field} deve ser texto não vazio com até {maximum} caracteres.")
        return value.strip()

    @_synchronized
    def _goals(self) -> dict[str, dict]:
        events = self.store.list_events(limit=1000, event_type=self.GOAL_EVENT)
        latest: dict[str, dict] = {}
        for event in events:
            payload = event.get("payload", {})
            goal = payload.get("goal") if isinstance(payload, dict) else None
            if not isinstance(goal, dict):
                continue
            goal_id = goal.get("goal_id")
            if isinstance(goal_id, str) and goal_id not in latest:
                latest[goal_id] = goal
        return latest

    @_synchronized
    def create_goal(
        self,
        title: str,
        description: str,
        *,
        priority: str = "normal",
        parent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        self._authorize("record_observation")
        title = self._text(title, "title", 160)
        description = self._text(description, "description", 2000)
        if not isinstance(priority, str) or priority not in self.PRIORITIES:
            raise ValueError("priority deve ser low, normal, high ou critical.")
        if parent_id is not None and (
            not isinstance(parent_id, str) or not parent_id.strip()
        ):
            raise ValueError("parent_id deve ser texto não vazio ou None.")
        goals = self._goals()
        if len(goals) >= self.MAX_GOALS:
            raise ValueError("Limite de objetivos ativos/históricos atingido.")
        if parent_id is not None and parent_id not in goals:
            raise ValueError("parent_id não corresponde a um objetivo existente.")
        if tags is None:
            tags = []
        if not isinstance(tags, list) or len(tags) > 20 or any(
            not isinstance(tag, str) or not tag.strip() or len(tag) > 60 for tag in tags
        ):
            raise ValueError("tags deve conter até 20 textos válidos.")
        now = _now()
        goal = {
            "goal_id": uuid.uuid4().hex,
            "title": title,
            "description": description,
            "priority": priority,
            "priority_rank": self.PRIORITIES[priority],
            "parent_id": parent_id,
            "tags": [tag.strip() for tag in tags],
            "status": "planned",
            "created_at": now,
            "updated_at": now,
            "history": [{"status": "planned", "at": now, "note": "goal_created"}],
            "execution_performed": False,
        }
        self.store.record_event(self.GOAL_EVENT, {"goal": goal})
        return {"status": "created", "goal": goal, "execution_performed": False}

    @_synchronized
    def transition_goal(self, goal_id: str, status: str, *, note: str = "") -> dict:
        self._authorize("record_observation")
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise ValueError("goal_id inválido.")
        if not isinstance(status, str) or status not in self.TRANSITIONS:
            raise ValueError("Estado de objetivo desconhecido.")
        if not isinstance(note, str) or len(note) > 500:
            raise ValueError("note deve conter até 500 caracteres.")
        goals = self._goals()
        current = goals.get(goal_id)
        if current is None:
            raise KeyError("Objetivo não encontrado.")
        if status not in self.TRANSITIONS[current["status"]]:
            raise ValueError(f"Transição inválida: {current['status']} -> {status}.")
        updated = dict(current)
        now = _now()
        history = list(current.get("history", []))
        history.append({"status": status, "at": now, "note": note.strip()})
        updated["history"] = history[-self.MAX_HISTORY:]
        updated["status"] = status
        updated["updated_at"] = now
        updated["execution_performed"] = False
        idempotency_key = (
            f"executive.goal.transition:{goal_id}:{current['updated_at']}"
        )
        try:
            recorded = self.store.record_event_once(
                self.GOAL_EVENT,
                idempotency_key,
                {"goal": updated},
            )
            if not recorded["created"]:
                raise ValueError(
                    "Transição já registrada por outro processo; recarregue o estado."
                )
        except ValueError as exc:
            # Another process may have committed a different transition from
            # the same goal revision. Never append a second competing state.
            latest = self._goals().get(goal_id)
            if latest is not None and latest.get("updated_at") != current["updated_at"]:
                raise ValueError(
                    "Objetivo alterado por outro processo; recarregue o estado antes de tentar novamente."
                ) from exc
            raise
        return {"status": "updated", "goal": updated, "execution_performed": False}

    @_synchronized
    def set_focus(self, goal_id: str | None, *, reason: str = "") -> dict:
        self._authorize("record_observation")
        if not isinstance(reason, str) or len(reason) > 500:
            raise ValueError("reason deve conter até 500 caracteres.")
        if goal_id is not None:
            if not isinstance(goal_id, str) or not goal_id.strip():
                raise ValueError("goal_id inválido.")
            goal = self._goals().get(goal_id)
            if goal is None or goal.get("status") != "active":
                raise ValueError("O foco só pode apontar para um objetivo ativo.")
        previous = self.store.list_events(
            limit=1, event_type=self.FOCUS_EVENT
        )
        revision = str(previous[0]["id"]) if previous else "initial"
        idempotency_key = f"executive.focus.revision:{revision}"
        try:
            recorded = self.store.record_event_once(
                self.FOCUS_EVENT,
                idempotency_key,
                {
                    "goal_id": goal_id,
                    "reason": reason.strip(),
                    "execution_performed": False,
                },
            )
        except ValueError as exc:
            raise ValueError(
                "Foco alterado por outro processo; recarregue o estado antes de tentar novamente."
            ) from exc
        if not recorded["created"]:
            raise ValueError(
                "Atualização de foco já registrada por outro processo; recarregue o estado."
            )
        return {
            "status": "focus_updated",
            "goal_id": goal_id,
            "event_id": recorded["event_id"],
        }

    @_synchronized
    def review_goal_transition(
        self,
        previous_goal_id: str,
        next_goal_id: str,
        *,
        relation_limit: int = 100,
        snapshots_per_goal: int = 5,
    ) -> dict:
        """Review explicit one-hop memory links around a goal change, read-only.

        This does not create relations, infer semantic similarity, change goal
        state, consolidate learning, or dispatch tools. Every returned edge
        remains an unverified candidate from MemoryGraph.
        """
        self._authorize("introspect")
        previous_id = self._text(previous_goal_id, "previous_goal_id", 64)
        next_id = self._text(next_goal_id, "next_goal_id", 64)
        if previous_id == next_id:
            raise ValueError("A meta anterior e a próxima precisam ser diferentes.")
        if (
            isinstance(relation_limit, bool)
            or not isinstance(relation_limit, int)
            or not 1 <= relation_limit <= 100
        ):
            raise ValueError("relation_limit deve estar entre 1 e 100.")
        if (
            isinstance(snapshots_per_goal, bool)
            or not isinstance(snapshots_per_goal, int)
            or not 1 <= snapshots_per_goal <= 10
        ):
            raise ValueError("snapshots_per_goal deve estar entre 1 e 10.")

        goals = self._goals()
        if previous_id not in goals:
            raise KeyError(previous_id)
        if next_id not in goals:
            raise KeyError(next_id)

        graph = getattr(self.cognitive, "memory_graph", None)
        list_relations = getattr(graph, "list_relations", None)
        if not callable(list_relations):
            return {
                "component": "ExecutiveEngine",
                "status": "memory_graph_unavailable",
                "previous_goal_id": previous_id,
                "next_goal_id": next_id,
                "candidate_links": [],
                "shared_candidate_event_ids": [],
                "execution_performed": False,
                "memory_modified": False,
                "goal_state_modified": False,
                "automatic_learning_consolidation": False,
                "automatic_tool_dispatch": False,
            }

        events = self.store.list_events(
            limit=1000,
            event_type=self.GOAL_EVENT,
        )
        event_ids_by_goal = {previous_id: [], next_id: []}
        for event in events:
            payload = event.get("payload", {})
            goal = payload.get("goal") if isinstance(payload, dict) else None
            goal_id = goal.get("goal_id") if isinstance(goal, dict) else None
            event_id = event.get("id")
            if (
                isinstance(goal_id, str)
                and goal_id in event_ids_by_goal
                and isinstance(event_id, int)
                and not isinstance(event_id, bool)
                and event_id > 0
            ):
                selected = event_ids_by_goal[goal_id]
                if len(selected) < snapshots_per_goal:
                    selected.append(event_id)

        sources = [
            (goal_id, event_id)
            for goal_id in (previous_id, next_id)
            for event_id in event_ids_by_goal[goal_id]
        ]
        links = []
        related_by_goal = {previous_id: set(), next_id: set()}
        history_may_be_incomplete = len(events) == 1000
        remaining_scan_budget = relation_limit
        seen_links = set()

        for index, (goal_id, source_event_id) in enumerate(sources):
            remaining_calls = len(sources) - index
            if remaining_scan_budget <= 0:
                history_may_be_incomplete = True
                break
            scan_limit = max(1, remaining_scan_budget // remaining_calls)
            review = list_relations(
                event_id=source_event_id,
                limit=scan_limit,
            )
            if not isinstance(review, dict):
                history_may_be_incomplete = True
                continue
            remaining_scan_budget -= scan_limit
            records = review.get("records", [])
            if not isinstance(records, list):
                history_may_be_incomplete = True
                continue
            history_may_be_incomplete = (
                history_may_be_incomplete
                or review.get("history_may_be_incomplete") is True
                or (
                    review.get("history_window_limit", scan_limit) == scan_limit
                    and len(records) >= scan_limit
                )
            )
            for relation in records:
                if not isinstance(relation, dict):
                    continue
                subject_id = relation.get("subject_event_id")
                object_id = relation.get("object_event_id")
                relation_event_id = relation.get("event_id")
                predicate = relation.get("predicate")
                if (
                    isinstance(subject_id, bool) or not isinstance(subject_id, int)
                    or subject_id <= 0
                    or isinstance(object_id, bool) or not isinstance(object_id, int)
                    or object_id <= 0
                    or isinstance(relation_event_id, bool)
                    or not isinstance(relation_event_id, int) or relation_event_id <= 0
                    or not isinstance(predicate, str)
                    or not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", predicate)
                    or relation.get("verified") is not False
                    or relation.get("epistemic_state") != "candidate_unverified"
                ):
                    continue
                if subject_id == source_event_id:
                    related_event_id, direction = object_id, "outgoing"
                elif object_id == source_event_id:
                    related_event_id, direction = subject_id, "incoming"
                else:
                    continue
                if related_event_id <= 0 or related_event_id == source_event_id:
                    continue
                identity = (
                    goal_id, source_event_id, related_event_id,
                    relation_event_id, predicate,
                )
                if identity in seen_links:
                    continue
                seen_links.add(identity)
                related_event = self.store.get_event(related_event_id)
                if related_event is None:
                    continue
                graph_event_types = getattr(graph, "GRAPH_EVENT_TYPES", ())
                related_event_type = related_event.get("event_type")
                if related_event_type in graph_event_types:
                    continue
                related_by_goal[goal_id].add(related_event_id)
                links.append({
                    "goal_role": "previous" if goal_id == previous_id else "next",
                    "goal_id": goal_id,
                    "goal_event_id": source_event_id,
                    "related_event_id": related_event_id,
                    "related_event_type": related_event_type,
                    "relation_event_id": relation_event_id,
                    "predicate": predicate,
                    "direction": direction,
                    "epistemic_state": "candidate_unverified",
                    "verified": False,
                })
                if len(links) >= relation_limit:
                    history_may_be_incomplete = True
                    break
            if len(links) >= relation_limit:
                break

        shared_ids = sorted(related_by_goal[previous_id] & related_by_goal[next_id])
        return {
            "component": "ExecutiveEngine",
            "status": "reviewed",
            "previous_goal_id": previous_id,
            "previous_goal_status": goals[previous_id].get("status"),
            "next_goal_id": next_id,
            "next_goal_status": goals[next_id].get("status"),
            "goal_event_snapshot_count": {
                "previous": len(event_ids_by_goal[previous_id]),
                "next": len(event_ids_by_goal[next_id]),
            },
            "candidate_link_count": len(links),
            "candidate_links": links,
            "shared_candidate_event_ids": shared_ids,
            "shared_candidate_event_count": len(shared_ids),
            "history_window_limit": 1000,
            "history_may_be_incomplete": history_may_be_incomplete,
            "traversal_depth": 1,
            "relation_scan_budget": relation_limit,
            "snapshots_per_goal_limit": snapshots_per_goal,
            "all_links_unverified": True,
            "memory_modified": False,
            "goal_state_modified": False,
            "automatic_learning_consolidation": False,
            "automatic_tool_dispatch": False,
            "execution_performed": False,
        }

    @_synchronized
    def snapshot(self) -> dict:
        self._authorize("introspect")
        goals = list(self._goals().values())
        goals.sort(
            key=lambda item: (
                -self.PRIORITIES.get(item.get("priority", "normal"), 0),
                item.get("created_at", ""),
            )
        )
        focus_events = self.store.list_events(limit=1, event_type=self.FOCUS_EVENT)
        focus_id = None
        if focus_events:
            payload = focus_events[0].get("payload", {})
            focus_id = payload.get("goal_id") if isinstance(payload, dict) else None
        by_status = {
            status: [goal for goal in goals if goal.get("status") == status]
            for status in self.TRANSITIONS
        }
        focus = next(
            (goal for goal in goals if goal.get("goal_id") == focus_id and goal.get("status") == "active"),
            None,
        )
        if focus is None:
            focus_id = None
        return {
            "component": "ExecutiveEngine",
            "version": self.VERSION,
            "goal_count": len(goals),
            "active_count": len(by_status["active"]),
            "blocked_count": len(by_status["blocked"]),
            "planned_count": len(by_status["planned"]),
            "focus": focus,
            "focus_goal_id": focus_id,
            "goals_by_status": by_status,
            "priority_order": [goal["goal_id"] for goal in goals],
            "working_memory_policy": {
                "persistent_goal_state": True,
                "append_only_history": True,
                "bounded_goal_history": self.MAX_HISTORY,
                "automatic_tool_dispatch": False,
                "automatic_goal_completion": False,
            },
            "execution_performed": False,
        }

    @staticmethod
    def _initiative_candidate_id(source: str, payload: dict) -> str:
        import hashlib
        import json

        raw = json.dumps(
            [source, payload],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @_synchronized
    def review_initiatives(self, experience_limit: int = 200) -> dict:
        """Derive reviewable initiative candidates from existing learning and capability audits.

        This is a read-only synthesis step: it does not create goals, consolidate
        learning, execute tools, or modify project files.
        """
        self._authorize("introspect")
        if (
            isinstance(experience_limit, bool)
            or not isinstance(experience_limit, int)
            or not 1 <= experience_limit <= 500
        ):
            raise ValueError("experience_limit deve estar entre 1 e 500.")

        experience_review = self.cognitive.review_experiences(
            limit=experience_limit
        )
        capability_review = self.cognitive.review_capabilities(persist=False)
        if not isinstance(experience_review, dict):
            raise TypeError("review_experiences deve retornar um dicionário.")
        if not isinstance(capability_review, dict):
            raise TypeError("review_capabilities deve retornar um dicionário.")

        experience_review_complete = experience_review.get(
            "review_complete"
        ) is True
        experience_candidates = experience_review.get("candidates", [])
        if not isinstance(experience_candidates, list):
            experience_candidates = []
        if not experience_review_complete:
            experience_candidates = []
        capability_assessment = capability_review.get("assessment", {})
        if not isinstance(capability_assessment, dict):
            capability_assessment = {}
        capability_candidates = capability_assessment.get("candidate_hypotheses", [])
        if not isinstance(capability_candidates, list):
            capability_candidates = []

        candidates = []
        inquiry_groups = {}
        for observation in self.store.list_observations(
            limit=100, category="self_inquiry"
        ):
            if not isinstance(observation, dict):
                continue
            question = observation.get("subject")
            data = observation.get("data", {})
            if not isinstance(question, str) or not question.strip():
                continue
            if isinstance(data, dict) and data.get("status") not in (
                None, "open_question"
            ):
                continue
            normalized_question = " ".join(question.casefold().split())
            group = inquiry_groups.setdefault(
                normalized_question,
                {"question": question.strip(), "observation_ids": [], "created_at": []},
            )
            observation_id = observation.get("id")
            if isinstance(observation_id, int) and not isinstance(observation_id, bool):
                group["observation_ids"].append(observation_id)
            created_at = observation.get("created_at")
            if isinstance(created_at, str):
                group["created_at"].append(created_at)

        for normalized_question, group in inquiry_groups.items():
            candidates.append({
                "candidate_id": "inquiry:" + self._initiative_candidate_id(
                    "self_inquiry", {"question": normalized_question}
                ),
                "kind": "self_inquiry",
                "title": f"Investigar lacuna: {group['question'][:100]}",
                "description": group["question"][:1000],
                "priority": "normal",
                "source": "persisted_self_inquiry",
                "evidence": {
                    "basis": "KnowledgeStore.observations",
                    "observation_ids": group["observation_ids"][:100],
                    "observation_count": len(group["observation_ids"]),
                    "latest_observation_at": max(group["created_at"], default=None),
                    "epistemic_state": "open_question_not_conclusion",
                },
                "status": "candidate_requires_human_review",
                "execution_performed": False,
            })

        introspection = getattr(self.cognitive, "introspection", None)
        self_model = None
        if introspection is not None:
            model_result = introspection.build_self_model(persist=False)
            if isinstance(model_result, dict):
                self_model = model_result
            open_questions = (
                self_model.get("open_questions", [])
                if self_model is not None else []
            )
            if isinstance(open_questions, list):
                for question in open_questions[:50]:
                    if not isinstance(question, str) or not question.strip():
                        continue
                    question = question.strip()
                    identity = {"question": " ".join(question.casefold().split())}
                    candidates.append({
                        "candidate_id": "inquiry:" + self._initiative_candidate_id(
                            "self_inquiry", identity
                        ),
                        "kind": "self_inquiry",
                        "title": f"Investigar lacuna: {question[:100]}",
                        "description": question[:1000],
                        "priority": "normal",
                        "source": "operational_self_model",
                        "evidence": {
                            "basis": "introspection.open_questions",
                            "epistemic_state": "open_question_not_conclusion",
                        },
                        "status": "candidate_requires_human_review",
                        "execution_performed": False,
                    })

        for item in experience_candidates:
            if not isinstance(item, dict):
                continue
            source_id = item.get("candidate_id")
            task_key = item.get("task_key")
            if not isinstance(source_id, str) or not isinstance(task_key, str):
                continue
            candidates.append({
                "candidate_id": f"experience:{source_id}",
                "kind": "experience_pattern",
                "title": f"Investigar padrão recorrente: {task_key[:100]}",
                "description": (
                    "Avaliar se o padrão recorrente observado pode melhorar "
                    "uma estratégia existente. Não aplicar automaticamente."
                ),
                "priority": "normal",
                "source": "adaptive_learning",
                "evidence": {
                    "candidate_id": source_id,
                    "event_ids": item.get("event_ids", []),
                    "episode_count": item.get("episode_count", 0),
                    "validated_episode_count": item.get("validated_episode_count", 0),
                    "learning_progress": item.get("learning_progress", 0.0),
                    "uncertainty_reducible": item.get("uncertainty_reducible", 0.0),
                    "prediction_regression": item.get("prediction_regression", 0.0),
                    "prediction_sample_count": item.get("prediction_sample_count", 0),
                    "prediction_progress_ambiguous": item.get("prediction_progress_ambiguous", False),
                    "evidence_state": item.get("evidence_state"),
                    "source_independence_verified": False,
                },
                "status": "candidate_requires_human_review",
                "execution_performed": False,
            })

        for item in capability_candidates:
            if not isinstance(item, dict):
                continue
            tool_id = item.get("tool_id")
            reason = item.get("reason", "")
            action = item.get("proposed_action", "")
            identity = {
                "tool_id": tool_id,
                "reason": reason,
                "proposed_action": action,
            }
            candidates.append({
                "candidate_id": "capability:" + self._initiative_candidate_id(
                    "capability_gap", identity
                ),
                "kind": "capability_gap",
                "title": f"Avaliar capacidade: {str(tool_id or 'não identificada')[:100]}",
                "description": (
                    str(action).strip()[:500]
                    or str(reason).strip()[:500]
                    or "Investigar uma lacuna identificada na auditoria de capacidades."
                ),
                "priority": (
                    item.get("priority")
                    if isinstance(item.get("priority"), str)
                    and item.get("priority") in self.PRIORITIES
                    else "normal"
                ),
                "source": "capability_audit",
                "evidence": {
                    "tool_id": tool_id,
                    "reason": str(reason)[:500],
                    "registered": item.get("registered", False),
                    "status": item.get("status", "candidate_not_tested"),
                },
                "status": "candidate_requires_human_review",
                "execution_performed": False,
            })

        # Detect status-level disagreement across distinct reports for the same
        # research plan. This is a review signal, not an automatic truth decision.
        research_event_limit = min(experience_limit, 500)
        research_events = self.store.list_events(
            limit=research_event_limit,
            event_type="adaptive.experience.recorded",
        )
        research_groups = {}
        for event in research_events:
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            references = payload.get("references", {})
            if not isinstance(references, dict):
                continue
            if references.get("reported_by") != (
                "caller_supplied_not_independently_verified"
            ):
                continue
            plan_id = references.get("research_plan_id")
            result_status = references.get("result_status")
            if (
                not isinstance(plan_id, str)
                or not re.fullmatch(r"research-[0-9a-f]{24}", plan_id)
                or not isinstance(result_status, str)
                or result_status not in {
                    "completed", "failed", "inconclusive", "blocked", "cancelled"
                }
            ):
                continue
            group = research_groups.setdefault(
                plan_id,
                {
                    "statuses": {},
                    "event_ids": [],
                    "attempt_ids": [],
                },
            )
            group["statuses"][result_status] = (
                group["statuses"].get(result_status, 0) + 1
            )
            event_id = event.get("id")
            if isinstance(event_id, int) and not isinstance(event_id, bool):
                group["event_ids"].append(event_id)
            attempt_id = references.get("attempt_id", "initial")
            if isinstance(attempt_id, str):
                group["attempt_ids"].append(attempt_id)

        mixed_plan_count = 0
        for plan_id, group in research_groups.items():
            status_counts = group["statuses"]
            if len(status_counts) <= 1:
                continue
            mixed_plan_count += 1
            statuses = sorted(status_counts)
            # Keep the candidate tag within ExecutiveEngine's 60-character
            # limit after the "initiative_candidate:" adoption prefix is added.
            candidate_id = "rconf:" + self._initiative_candidate_id(
                "research_result_status_conflict",
                {"plan_id": plan_id, "statuses": statuses},
            )
            short_plan = plan_id[-8:]
            candidates.append({
                "candidate_id": candidate_id,
                "kind": "research_result_conflict",
                "title": f"Reconciliar relatos divergentes do plano {short_plan}",
                "description": (
                    "Tentativas do mesmo plano de pesquisa registraram status "
                    f"divergentes ({', '.join(statuses)}). Revisar métodos, "
                    "condições e evidências antes de qualquer conclusão."
                ),
                "priority": "normal",
                "source": "research_result_feedback",
                "evidence": {
                    "basis": "KnowledgeStore.events",
                    "research_plan_id": plan_id,
                    "event_ids": sorted(group["event_ids"])[:100],
                    "attempt_ids": sorted(set(group["attempt_ids"]))[:100],
                    "result_status_counts": status_counts,
                    "result_statuses": statuses,
                    "epistemic_state": (
                        "caller_reported_status_conflict_requires_review"
                    ),
                    "report_provenance": (
                        "caller_supplied_not_independently_verified"
                    ),
                    "source_independence_verified": False,
                },
                "status": "candidate_requires_human_review",
                "execution_performed": False,
            })

        research_history_status = (
            "reviewed_window_may_be_truncated"
            if len(research_events) == research_event_limit
            else "reviewed"
        )

        candidates.sort(
            key=lambda item: (
                -self.PRIORITIES.get(item["priority"], 0),
                item["kind"],
                item["candidate_id"],
            )
        )
        unique_candidates = []
        seen_candidate_ids = set()
        for item in candidates:
            candidate_id = item["candidate_id"]
            if candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            unique_candidates.append(item)
        duplicate_count = len(candidates) - len(unique_candidates)
        candidates = unique_candidates

        adopted_ids = set()
        for goal in self._goals().values():
            tags = goal.get("tags", [])
            if not isinstance(tags, list):
                continue
            for tag in tags:
                if isinstance(tag, str) and tag.startswith("initiative_candidate:"):
                    adopted_ids.add(tag.split(":", 1)[1])
        before_adoption_filter = len(candidates)
        candidates = [
            item for item in candidates
            if item["candidate_id"] not in adopted_ids
        ]

        return {
            "component": "ExecutiveEngine",
            "status": "reviewed",
            "candidate_count": len(candidates),
            "suppressed_adopted_count": before_adoption_filter - len(candidates),
            "suppressed_duplicate_count": duplicate_count,
            "candidates": candidates,
            "sources": {
                "experience_replay": (
                    experience_review.get("status", "unavailable")
                    if experience_review_complete
                    else "reviewed_history_incomplete"
                ),
                "experience_replay_complete": experience_review_complete,
                "experience_replay_window_truncated": experience_review.get(
                    "window_truncated", False
                ) is True,
                "capability_audit": capability_review.get("status", "unavailable"),
                "operational_self_model": (
                    "reviewed" if self_model is not None else "unavailable"
                ),
                "research_result_history": research_history_status,
            },
            "experience_replay_history": {
                "status": (
                    "complete" if experience_review_complete else "incomplete"
                ),
                "events_examined": experience_review.get("events_examined"),
                "total_recorded_episodes": experience_review.get(
                    "total_recorded_episodes"
                ),
                "window_limit": experience_review.get("window_limit"),
                "window_truncated": experience_review.get(
                    "window_truncated", False
                ) is True,
                "candidate_proposals_suppressed": not experience_review_complete,
            },
            "research_result_history": {
                "status": research_history_status,
                "event_count": len(research_events),
                "event_window": research_event_limit,
                "mixed_plan_count": mixed_plan_count,
                "window_may_be_truncated": (
                    len(research_events) == research_event_limit
                ),
                "automatic_conflict_resolution": False,
            },
            "initiative_policy": {
                "derived_from_existing_subsystems": True,
                "automatic_goal_creation": False,
                "automatic_learning_consolidation": False,
                "automatic_tool_dispatch": False,
                "automatic_result_truth_selection": False,
                "automatic_conflict_resolution": False,
                "human_approval_required_for_adoption": True,
                "evidence_independence_verified": False,
            },
            "execution_performed": False,
            "memory_modified": False,
        }

    @_synchronized
    def adopt_initiative(
        self, candidate_id: str, *, approved: bool = False
    ) -> dict:
        """Convert a freshly revalidated initiative into a planned executive goal."""
        if approved is not True:
            raise PermissionError("Adoção de iniciativa exige aprovação explícita.")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id.strip()
            or len(candidate_id) > 64
        ):
            raise ValueError("candidate_id inválido.")

        adoption_tag = f"initiative_candidate:{candidate_id}"
        for goal in self._goals().values():
            tags = goal.get("tags", [])
            if isinstance(tags, list) and adoption_tag in tags:
                return {
                    "status": "initiative_already_adopted",
                    "candidate_id": candidate_id,
                    "goal": goal,
                    "execution_performed": False,
                    "tool_dispatch_performed": False,
                }

        review = self.review_initiatives()
        candidate = next(
            (
                item for item in review["candidates"]
                if item["candidate_id"] == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "Iniciativa não encontrada na revisão atual; nenhuma meta foi criada."
            )

        # Construct the goal only after the fresh review and explicit approval.
        # record_event_once enforces one adoption across independent processes.
        now = _now()
        goal = {
            "goal_id": uuid.uuid4().hex,
            "title": candidate["title"],
            "description": candidate["description"],
            "priority": candidate["priority"],
            "priority_rank": self.PRIORITIES[candidate["priority"]],
            "parent_id": None,
            "tags": [
                "initiative",
                candidate["source"],
                candidate["kind"],
                adoption_tag,
            ],
            "status": "planned",
            "created_at": now,
            "updated_at": now,
            "history": [{"status": "planned", "at": now, "note": "goal_created"}],
            "execution_performed": False,
        }
        try:
            recorded = self.store.record_event_once(
                self.GOAL_EVENT,
                f"executive.initiative.adoption:{candidate_id}",
                {"goal": goal},
            )
        except ValueError:
            # A concurrent adopter may have won with a different timestamp/ID.
            for existing_goal in self._goals().values():
                tags = existing_goal.get("tags", [])
                if isinstance(tags, list) and adoption_tag in tags:
                    return {
                        "status": "initiative_already_adopted",
                        "candidate_id": candidate_id,
                        "goal": existing_goal,
                        "execution_performed": False,
                        "tool_dispatch_performed": False,
                    }
            raise

        if not recorded["created"]:
            for existing_goal in self._goals().values():
                tags = existing_goal.get("tags", [])
                if isinstance(tags, list) and adoption_tag in tags:
                    goal = existing_goal
                    break
            else:
                raise RuntimeError(
                    "Registro idempotente existe, mas a meta não foi encontrada."
                )
            status = "initiative_already_adopted"
        else:
            status = "initiative_adopted_as_planned_goal"

        return {
            "status": status,
            "candidate_id": candidate_id,
            "goal": goal,
            "execution_performed": False,
            "tool_dispatch_performed": False,
        }

    @_synchronized
    def build_context(self, max_chars: int = 4000) -> dict:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 256 <= max_chars <= 8000:
            raise ValueError("max_chars deve estar entre 256 e 8000.")
        snapshot = self.snapshot()
        lines = ["Estado executivo persistente do Mahoraga:"]
        focus = snapshot["focus"]
        if focus:
            lines.append(f"Foco atual: {focus['title']} (prioridade {focus['priority']}).")
        else:
            lines.append("Foco atual: nenhum objetivo ativo selecionado.")
        for status in ("active", "blocked", "planned", "suspended"):
            items = snapshot["goals_by_status"][status]
            if items:
                lines.append(f"{status}:")
                for goal in items[:8]:
                    lines.append(
                        f"- {goal['title']} [prioridade={goal['priority']}; id={goal['goal_id']}]"
                    )
        lines.append("Não presumir que um objetivo registrado já foi executado.")
        lines.append("Objetivos e contexto não autorizam execução de ferramentas.")
        context = "\n".join(lines)
        truncated = len(context) > max_chars
        if truncated:
            context = context[:max_chars].rsplit("\n", 1)[0]
        return {
            "status": "ready",
            "context": context,
            "context_chars": len(context),
            "truncated": truncated,
            "execution_performed": False,
            "snapshot": snapshot,
        }

    @_synchronized
    def status(self) -> dict:
        snapshot = self.snapshot()
        return {
            "component": "ExecutiveEngine",
            "version": self.VERSION,
            "goal_count": snapshot["goal_count"],
            "active_count": snapshot["active_count"],
            "blocked_count": snapshot["blocked_count"],
            "focus_goal_id": snapshot["focus_goal_id"],
            "automatic_tool_dispatch": False,
            "execution_performed": False,
        }
