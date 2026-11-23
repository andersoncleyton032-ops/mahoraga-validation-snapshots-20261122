"""Append-only associative memory graph backed by the canonical KnowledgeStore.

Relations and interpretations are candidate records, never trusted facts.
The graph adds no tables and never mutates the source episode/event.
"""
from __future__ import annotations

import hashlib
import math
import json
import re
from typing import Any

from .graph_algorithms import bounded_simple_paths


class MemoryGraphError(ValueError):
    """Invalid memory graph node, edge, or interpretation."""


class MemoryGraphEngine:
    VERSION = "0.1.0"
    RELATION_EVENT_TYPE = "memory.relation.proposed"
    INTERPRETATION_EVENT_TYPE = "memory.interpretation.recorded"
    CHUNK_ANCHOR_EVENT_TYPE = "memory.chunk_anchor.proposed"
    MAX_RECORDS = 1000
    MAX_EVIDENCE_EVENTS = 16
    GRAPH_EVENT_TYPES = frozenset({
        RELATION_EVENT_TYPE,
        INTERPRETATION_EVENT_TYPE,
        CHUNK_ANCHOR_EVENT_TYPE,
    })

    def __init__(self, cognitive):
        self.cognitive = cognitive
        self.store = cognitive.store

    @staticmethod
    def _event_id(value: Any, field: str = "event_id") -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > 9_223_372_036_854_775_807
        ):
            raise MemoryGraphError(f"{field} deve ser um inteiro positivo representável pelo SQLite.")
        return value

    @staticmethod
    def _text(value: Any, field: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise MemoryGraphError(f"{field} deve ser texto não vazio com até {maximum} caracteres.")
        return value.strip()

    @classmethod
    def _validate_json(cls, value: Any, depth: int = 0) -> None:
        if depth > 12:
            raise MemoryGraphError("Profundidade máxima do payload excedida.")
        if value is None or isinstance(value, (str, bool, int)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise MemoryGraphError("Valores numéricos não finitos não são permitidos.")
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                cls._validate_json(item, depth + 1)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise MemoryGraphError("Chaves de contexto devem ser texto.")
                cls._validate_json(item, depth + 1)
            return
        raise MemoryGraphError(f"Tipo não serializável: {type(value).__name__}.")

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> tuple[str, str]:
        MemoryGraphEngine._validate_json(payload)
        try:
            raw = json.dumps(
                payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise MemoryGraphError("Payload da memória associativa não é JSON válido.") from exc
        return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()

    def _require_event(self, event_id: Any, field: str = "event_id") -> dict[str, Any]:
        normalized = self._event_id(event_id, field)
        event = self.store.get_event(normalized)
        if event is None:
            raise MemoryGraphError(f"{field}={normalized} não existe no KnowledgeStore.")
        return event

    def _require_source_event(self, event_id: Any, field: str = "event_id") -> dict[str, Any]:
        event = self._require_event(event_id, field)
        if event.get("event_type") in self.GRAPH_EVENT_TYPES:
            raise MemoryGraphError(
                f"{field} deve apontar para um evento de origem, não para metadados do próprio MemoryGraph."
            )
        return event

    def _evidence_ids(self, values: Any) -> list[int]:
        if values is None:
            values = []
        if not isinstance(values, (list, tuple)) or len(values) > self.MAX_EVIDENCE_EVENTS:
            raise MemoryGraphError(
                f"evidence_event_ids deve conter até {self.MAX_EVIDENCE_EVENTS} IDs."
            )
        result = sorted({self._event_id(value, "evidence_event_id") for value in values})
        for event_id in result:
            self._require_source_event(event_id, "evidence_event_id")
        return result

    def record_relation(
        self,
        subject_event_id: int,
        predicate: str,
        object_event_id: int,
        *,
        context: dict[str, Any] | None = None,
        evidence_event_ids: list[int] | tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        """Append a candidate edge between two immutable events.

        No caller-supplied verified/approved flag is accepted. Every edge
        remains candidate_unverified until a future trusted verifier exists.
        """
        self.cognitive._authorize("record_observation")
        subject = self._event_id(subject_event_id, "subject_event_id")
        object_ = self._event_id(object_event_id, "object_event_id")
        if subject == object_:
            raise MemoryGraphError("Uma relação não pode ligar um evento a ele próprio.")
        self._require_source_event(subject, "subject_event_id")
        self._require_source_event(object_, "object_event_id")
        predicate = self._text(predicate, "predicate", 64).casefold()
        if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", predicate):
            raise MemoryGraphError("predicate deve ser um identificador semântico simples.")
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise MemoryGraphError("context deve ser um objeto JSON.")
        canonical_context, _ = self._canonical(context)
        if len(canonical_context.encode("utf-8")) > 4096:
            raise MemoryGraphError("context excede 4096 bytes.")
        evidence = self._evidence_ids(evidence_event_ids)
        if subject not in evidence:
            evidence.append(subject)
        if object_ not in evidence:
            evidence.append(object_)
        evidence = sorted(set(evidence))
        if len(evidence) > self.MAX_EVIDENCE_EVENTS:
            raise MemoryGraphError(
                f"Uma relação pode citar até {self.MAX_EVIDENCE_EVENTS} eventos de evidência."
            )

        base = {
            "schema": "mahoraga.memory_relation",
            "version": self.VERSION,
            "subject_event_id": subject,
            "predicate": predicate,
            "object_event_id": object_,
            "context": context,
            "evidence_event_ids": evidence,
            "epistemic_state": "candidate_unverified",
            "verified": False,
            "source_identity_verified": False,
            "promotion_performed": False,
        }
        _, digest = self._canonical(base)
        payload = {**base, "relation_id": digest[:32]}
        recorded = self.store.record_event_once(
            self.RELATION_EVENT_TYPE,
            f"memory.relation:{digest}",
            payload,
        )
        return {
            "status": "recorded" if recorded["created"] else "already_recorded",
            "event_id": recorded["event_id"],
            "relation_id": payload["relation_id"],
            "epistemic_state": "candidate_unverified",
            "verified": False,
            "promotion_performed": False,
        }

    def record_interpretation(
        self,
        source_event_id: int,
        interpretation: str,
        *,
        rationale: str = "",
        support_event_ids: list[int] | tuple[int, ...] | None = None,
        supersedes_interpretation_event_id: int | None = None,
    ) -> dict[str, Any]:
        """Append a versioned interpretation without changing its source event."""
        self.cognitive._authorize("record_observation")
        source = self._event_id(source_event_id, "source_event_id")
        self._require_source_event(source, "source_event_id")
        interpretation = self._text(interpretation, "interpretation", 5000)
        if rationale is None:
            rationale = ""
        if not isinstance(rationale, str) or len(rationale) > 2000:
            raise MemoryGraphError("rationale deve conter até 2000 caracteres.")
        support = self._evidence_ids(support_event_ids)
        if source not in support:
            support.append(source)
        support = sorted(set(support))
        if len(support) > self.MAX_EVIDENCE_EVENTS:
            raise MemoryGraphError(
                f"Uma interpretação pode citar até {self.MAX_EVIDENCE_EVENTS} eventos de suporte."
            )

        supersedes = None
        if supersedes_interpretation_event_id is not None:
            supersedes = self._event_id(
                supersedes_interpretation_event_id,
                "supersedes_interpretation_event_id",
            )
            previous = self._require_event(supersedes, "supersedes_interpretation_event_id")
            previous_payload = previous.get("payload", {})
            if (
                previous.get("event_type") != self.INTERPRETATION_EVENT_TYPE
                or not isinstance(previous_payload, dict)
                or previous_payload.get("source_event_id") != source
            ):
                raise MemoryGraphError(
                    "A interpretação substituída precisa pertencer ao mesmo evento de origem."
                )

        base = {
            "schema": "mahoraga.memory_interpretation",
            "version": self.VERSION,
            "source_event_id": source,
            "interpretation": interpretation,
            "rationale": rationale,
            "support_event_ids": support,
            "supersedes_interpretation_event_id": supersedes,
            "epistemic_state": "candidate_unverified",
            "verified": False,
            "source_identity_verified": False,
            "semantic_promotion_performed": False,
        }
        _, digest = self._canonical(base)
        payload = {**base, "interpretation_id": digest[:32]}
        recorded = self.store.record_event_once(
            self.INTERPRETATION_EVENT_TYPE,
            f"memory.interpretation:{digest}",
            payload,
        )
        return {
            "status": "recorded" if recorded["created"] else "already_recorded",
            "event_id": recorded["event_id"],
            "interpretation_id": payload["interpretation_id"],
            "source_event_id": source,
            "epistemic_state": "candidate_unverified",
            "verified": False,
            "semantic_promotion_performed": False,
        }

    def record_chunk_anchor(
        self,
        source_event_id: int,
        document_id: int,
        chunk_index: int,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an unverified, hash-bound link from an episode to one document chunk."""
        self.cognitive._authorize("record_observation")
        source = self._event_id(source_event_id, "source_event_id")
        self._require_source_event(source, "source_event_id")
        if (
            isinstance(document_id, bool)
            or not isinstance(document_id, int)
            or document_id <= 0
        ):
            raise MemoryGraphError("document_id deve ser um inteiro positivo.")
        if (
            isinstance(chunk_index, bool)
            or not isinstance(chunk_index, int)
            or chunk_index < 0
        ):
            raise MemoryGraphError("chunk_index deve ser um inteiro não negativo.")
        chunk = self.cognitive.knowledge.get_chunk(document_id, chunk_index)
        if chunk is None or chunk.get("status") != "prepared":
            raise MemoryGraphError("O fragmento não existe ou não está preparado.")
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise MemoryGraphError("context deve ser um objeto JSON.")
        canonical_context, _ = self._canonical(context)
        if len(canonical_context.encode("utf-8")) > 4096:
            raise MemoryGraphError("context excede 4096 bytes.")
        base = {
            "schema": "mahoraga.memory_chunk_anchor",
            "version": self.VERSION,
            "source_event_id": source,
            "document_id": chunk["document_id"],
            "document_sha256": chunk["document_sha256"],
            "chunk_index": chunk["chunk_index"],
            "chunk_sha256": chunk["chunk_sha256"],
            "context": context,
            "epistemic_state": "candidate_unverified",
            "verified": False,
            "source_identity_verified": False,
            "promotion_performed": False,
        }
        _, digest = self._canonical(base)
        payload = {**base, "anchor_id": digest[:32]}
        recorded = self.store.record_event_once(
            self.CHUNK_ANCHOR_EVENT_TYPE,
            f"memory.chunk_anchor:{digest}",
            payload,
        )
        return {
            "status": "recorded" if recorded["created"] else "already_recorded",
            "event_id": recorded["event_id"],
            "anchor_id": payload["anchor_id"],
            "epistemic_state": "candidate_unverified",
            "verified": False,
        }

    def expand_chunk_associations(
        self,
        matches: list[dict[str, Any]],
        *,
        max_related_events: int = 10,
    ) -> dict[str, Any]:
        """Expand retrieved chunks by one graph hop under a global work budget.

        Only exact document/chunk hashes are eligible. Traversal is read-only,
        bounded, non-recursive, and never promotes candidate relations to facts.
        max_related_events is a total budget across the entire retrieval, not
        a per-anchor multiplier.
        """
        self.cognitive._authorize("read_project")
        if not isinstance(matches, list) or len(matches) > 20:
            raise MemoryGraphError("matches deve ser uma lista com até 20 fragmentos.")
        if (
            isinstance(max_related_events, bool)
            or not isinstance(max_related_events, int)
            or not 0 <= max_related_events <= 50
        ):
            raise MemoryGraphError("max_related_events deve estar entre 0 e 50.")

        match_keys = set()
        for match in matches:
            if not isinstance(match, dict):
                continue
            document_id = match.get("document_id")
            document_hash = match.get("document_sha256")
            chunk_index = match.get("chunk_index")
            chunk_hash = match.get("chunk_sha256")
            if (
                isinstance(document_id, bool) or not isinstance(document_id, int)
                or document_id <= 0
                or isinstance(chunk_index, bool) or not isinstance(chunk_index, int)
                or chunk_index < 0
                or not isinstance(document_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", document_hash)
                or not isinstance(chunk_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", chunk_hash)
            ):
                continue
            match_keys.add((document_id, document_hash, chunk_index, chunk_hash))

        anchors = self.store.list_events(
            limit=self.MAX_RECORDS,
            event_type=self.CHUNK_ANCHOR_EVENT_TYPE,
        ) if match_keys else []
        relation_events = self.store.list_events(
            limit=self.MAX_RECORDS,
            event_type=self.RELATION_EVENT_TYPE,
        ) if anchors and max_related_events else []

        # Resolve all source/target event IDs in bounded batches. The former
        # implementation issued two SQLite reads per relation plus one read per
        # returned neighbor, creating an N+1 query pattern under a 1,000-row cap.
        event_ids = set()
        for relation_event in relation_events:
            payload = relation_event.get("payload", {})
            if not isinstance(payload, dict) or payload.get("verified") is not False:
                continue
            subject = payload.get("subject_event_id")
            object_ = payload.get("object_event_id")
            predicate = payload.get("predicate")
            if (
                isinstance(subject, bool) or not isinstance(subject, int)
                or not 0 < subject <= 9_223_372_036_854_775_807
                or isinstance(object_, bool) or not isinstance(object_, int)
                or not 0 < object_ <= 9_223_372_036_854_775_807
                or subject == object_
                or not isinstance(predicate, str)
            ):
                continue
            event_ids.update((subject, object_))

        for anchor in anchors:
            payload = anchor.get("payload", {})
            source_event_id = payload.get("source_event_id") if isinstance(payload, dict) else None
            if (
                isinstance(source_event_id, int)
                and not isinstance(source_event_id, bool)
                and 0 < source_event_id <= 9_223_372_036_854_775_807
            ):
                event_ids.add(source_event_id)

        events_by_id = self.store.get_events(sorted(event_ids)) if event_ids else {}

        # Build adjacency once. Only source events from the canonical Store are
        # eligible; graph metadata events can never become graph vertices.
        adjacency: dict[int, list[dict[str, Any]]] = {}
        for relation_event in relation_events:
            payload = relation_event.get("payload", {})
            if not isinstance(payload, dict) or payload.get("verified") is not False:
                continue
            subject = payload.get("subject_event_id")
            object_ = payload.get("object_event_id")
            predicate = payload.get("predicate")
            if (
                isinstance(subject, bool) or not isinstance(subject, int)
                or not 0 < subject <= 9_223_372_036_854_775_807
                or isinstance(object_, bool) or not isinstance(object_, int)
                or not 0 < object_ <= 9_223_372_036_854_775_807
                or subject == object_
                or not isinstance(predicate, str)
            ):
                continue
            subject_event = events_by_id.get(subject)
            object_event = events_by_id.get(object_)
            if (
                subject_event is None or object_event is None
                or subject_event.get("event_type") in self.GRAPH_EVENT_TYPES
                or object_event.get("event_type") in self.GRAPH_EVENT_TYPES
            ):
                continue
            adjacency.setdefault(subject, []).append({
                "event_id": object_, "direction": "outgoing",
                "relation_event": relation_event, "predicate": predicate,
            })
            adjacency.setdefault(object_, []).append({
                "event_id": subject, "direction": "incoming",
                "relation_event": relation_event, "predicate": predicate,
            })

        associations = []
        seen_sources: set[int] = set()
        seen_related: set[tuple[int, int, int]] = set()
        remaining_related = max_related_events
        for anchor in anchors:
            if len(associations) >= 20:
                break
            payload = anchor.get("payload", {})
            if not isinstance(payload, dict):
                continue
            identity = (
                payload.get("document_id"), payload.get("document_sha256"),
                payload.get("chunk_index"), payload.get("chunk_sha256"),
            )
            if identity not in match_keys or payload.get("verified") is not False:
                continue
            source_event_id = payload.get("source_event_id")
            if (
                isinstance(source_event_id, bool)
                or not isinstance(source_event_id, int)
                or source_event_id <= 0
                or source_event_id in seen_sources
            ):
                continue
            source_event = events_by_id.get(source_event_id)
            if (
                source_event is None
                or source_event.get("event_type") in self.GRAPH_EVENT_TYPES
            ):
                continue
            seen_sources.add(source_event_id)
            relation_records = []
            for neighbor in adjacency.get(source_event_id, []):
                if remaining_related <= 0:
                    break
                related_id = neighbor["event_id"]
                relation_event = neighbor["relation_event"]
                edge_identity = (source_event_id, related_id, relation_event["id"])
                if edge_identity in seen_related:
                    continue
                related_event = events_by_id.get(related_id)
                if (
                    related_event is None
                    or related_event.get("event_type") in self.GRAPH_EVENT_TYPES
                ):
                    continue
                seen_related.add(edge_identity)
                relation_records.append({
                    "event_id": related_id,
                    "direction": neighbor["direction"],
                    "predicate": neighbor["predicate"],
                    "epistemic_state": "candidate_unverified",
                    "event": related_event,
                    "relation_event": relation_event,
                    "verified": False,
                })
                remaining_related -= 1
            associations.append({
                "anchor_event_id": anchor["id"],
                "source_event": source_event,
                "relations": relation_records,
                "document_id": identity[0],
                "document_sha256": identity[1],
                "chunk_index": identity[2],
                "chunk_sha256": identity[3],
                "epistemic_state": "candidate_unverified",
                "verified": False,
            })
        return {
            "status": "completed",
            "association_count": len(associations),
            "related_event_count": sum(len(item["relations"]) for item in associations),
            "associations": associations,
            "history_window_limit": self.MAX_RECORDS,
            "history_may_be_incomplete": (
                len(anchors) == self.MAX_RECORDS
                or len(relation_events) == self.MAX_RECORDS
            ),
            "traversal_depth": 1,
            "association_limit": 20,
            "related_event_budget": max_related_events,
            "persistent_write_performed": False,
            "all_associations_unverified": True,
        }

    def list_relations(
        self,
        *,
        event_id: int | None = None,
        predicate: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_RECORDS:
            raise MemoryGraphError(f"limit deve ser inteiro entre 1 e {self.MAX_RECORDS}.")
        selected_event = self._event_id(event_id) if event_id is not None else None
        selected_predicate = (
            self._text(predicate, "predicate", 64).casefold()
            if predicate is not None else None
        )
        events = self.store.list_events(
            limit=limit, event_type=self.RELATION_EVENT_TYPE
        )
        records = []
        for event in events:
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if selected_event is not None and selected_event not in (
                payload.get("subject_event_id"), payload.get("object_event_id")
            ):
                continue
            if selected_predicate is not None and payload.get("predicate") != selected_predicate:
                continue
            records.append({
                "event_id": event["id"],
                **payload,
                "verified": False,
            })
        return {
            "status": "completed",
            "records": records,
            "count": len(records),
            "history_window_limit": limit,
            "history_may_be_incomplete": len(events) == limit,
            "all_records_are_unverified_candidates": True,
        }

    def related_events(
        self,
        event_id: int,
        *,
        predicate: str | None = None,
        direction: str = "both",
        limit: int = 100,
    ) -> dict[str, Any]:
        event_id = self._event_id(event_id)
        self._require_source_event(event_id, "event_id")
        if direction not in {"both", "outgoing", "incoming"}:
            raise MemoryGraphError("direction deve ser both, outgoing ou incoming.")
        relations = self.list_relations(
            event_id=event_id, predicate=predicate, limit=limit
        )["records"]
        neighbors = []
        for relation in relations:
            if direction in {"both", "outgoing"} and relation["subject_event_id"] == event_id:
                neighbors.append({
                    "event_id": relation["object_event_id"],
                    "direction": "outgoing",
                    "relation_event_id": relation["event_id"],
                    "predicate": relation["predicate"],
                    "epistemic_state": "candidate_unverified",
                })
            if direction in {"both", "incoming"} and relation["object_event_id"] == event_id:
                neighbors.append({
                    "event_id": relation["subject_event_id"],
                    "direction": "incoming",
                    "relation_event_id": relation["event_id"],
                    "predicate": relation["predicate"],
                    "epistemic_state": "candidate_unverified",
                })
        return {
            "status": "completed",
            "source_event_id": event_id,
            "neighbors": neighbors,
            "count": len(neighbors),
            "verified": False,
        }


    def trace_paths(
        self,
        source_event_id: int,
        target_event_id: int,
        *,
        predicate: str | None = None,
        direction: str = "outgoing",
        max_hops: int = 4,
        max_paths: int = 10,
        max_edge_visits: int = 5000,
        history_limit: int = 1000,
    ) -> dict[str, Any]:
        """Trace bounded paths through unverified event relations, read-only.

        Paths are explanations of candidate associations, not proofs of facts
        or causality. Traversal never promotes an edge and never writes to the
        canonical Store.
        """
        self.cognitive._authorize("read_project")
        source = self._event_id(source_event_id, "source_event_id")
        target = self._event_id(target_event_id, "target_event_id")
        if source == target:
            raise MemoryGraphError("source_event_id e target_event_id devem ser diferentes.")
        if direction not in {"outgoing", "incoming", "both"}:
            raise MemoryGraphError("direction deve ser outgoing, incoming ou both.")
        if predicate is not None:
            predicate = self._text(predicate, "predicate", 64).casefold()
            if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", predicate):
                raise MemoryGraphError("predicate deve ser um identificador semântico simples.")
        for field, value, minimum, maximum in (
            ("max_hops", max_hops, 1, 6),
            ("max_paths", max_paths, 1, 20),
            ("max_edge_visits", max_edge_visits, 1, 5000),
            ("history_limit", history_limit, 1, self.MAX_RECORDS),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise MemoryGraphError(
                    f"{field} deve ser inteiro entre {minimum} e {maximum}."
                )

        relation_events = self.store.list_events(
            limit=history_limit,
            event_type=self.RELATION_EVENT_TYPE,
        )
        candidates = []
        endpoint_ids = {source, target}
        for relation_event in relation_events:
            payload = relation_event.get("payload", {})
            if (
                not isinstance(payload, dict)
                or payload.get("verified") is not False
                or payload.get("epistemic_state", "candidate_unverified")
                != "candidate_unverified"
            ):
                continue
            subject = payload.get("subject_event_id")
            object_ = payload.get("object_event_id")
            relation_predicate = payload.get("predicate")
            if (
                isinstance(subject, bool)
                or not isinstance(subject, int)
                or not 0 < subject <= 9_223_372_036_854_775_807
                or isinstance(object_, bool)
                or not isinstance(object_, int)
                or not 0 < object_ <= 9_223_372_036_854_775_807
                or subject == object_
                or not isinstance(relation_predicate, str)
                or not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", relation_predicate)
            ):
                continue
            if predicate is not None and relation_predicate != predicate:
                continue
            raw_evidence = payload.get("evidence_event_ids", [])
            if not isinstance(raw_evidence, (list, tuple)) or len(raw_evidence) > self.MAX_EVIDENCE_EVENTS:
                raw_evidence = []
            evidence_ids = sorted({
                item for item in raw_evidence
                if (
                    isinstance(item, int)
                    and not isinstance(item, bool)
                    and 0 < item <= 9_223_372_036_854_775_807
                )
            })
            endpoint_ids.update((subject, object_))
            candidates.append({
                "relation_event": relation_event,
                "subject_event_id": subject,
                "object_event_id": object_,
                "predicate": relation_predicate,
                "evidence_event_ids": evidence_ids,
            })

        events_by_id = self.store.get_events(sorted(endpoint_ids))
        source_event = events_by_id.get(source)
        target_event = events_by_id.get(target)
        if source_event is None:
            raise MemoryGraphError(f"source_event_id={source} não existe no KnowledgeStore.")
        if target_event is None:
            raise MemoryGraphError(f"target_event_id={target} não existe no KnowledgeStore.")
        if (
            source_event.get("event_type") in self.GRAPH_EVENT_TYPES
            or target_event.get("event_type") in self.GRAPH_EVENT_TYPES
        ):
            raise MemoryGraphError("Os extremos precisam ser eventos de origem, não metadados do MemoryGraph.")

        adjacency: dict[int, list[dict[str, Any]]] = {}
        usable_edge_count = 0
        for item in candidates:
            subject = item["subject_event_id"]
            object_ = item["object_event_id"]
            subject_event = events_by_id.get(subject)
            object_event = events_by_id.get(object_)
            if (
                subject_event is None
                or object_event is None
                or subject_event.get("event_type") in self.GRAPH_EVENT_TYPES
                or object_event.get("event_type") in self.GRAPH_EVENT_TYPES
            ):
                continue
            usable_edge_count += 1
            relation_event = item["relation_event"]
            base_edge = {
                "relation_event_id": relation_event["id"],
                "subject_event_id": subject,
                "object_event_id": object_,
                "predicate": item["predicate"],
                "evidence_event_ids": item["evidence_event_ids"],
                "created_at": relation_event.get("created_at"),
                "epistemic_state": "candidate_unverified",
                "verified": False,
            }
            if direction in {"outgoing", "both"}:
                adjacency.setdefault(subject, []).append({
                    **base_edge,
                    "target": object_,
                    "traversal_direction": "outgoing",
                })
            if direction in {"incoming", "both"}:
                adjacency.setdefault(object_, []).append({
                    **base_edge,
                    "target": subject,
                    "traversal_direction": "incoming",
                })

        for edges in adjacency.values():
            edges.sort(key=lambda edge: (
                edge["target"],
                edge["predicate"],
                edge["relation_event_id"],
                edge["traversal_direction"],
            ))

        search = bounded_simple_paths(
            adjacency,
            source,
            target,
            max_hops=max_hops,
            max_paths=max_paths,
            max_edge_visits=max_edge_visits,
        )
        selected_evidence_ids = sorted({
            evidence_id
            for path in search["paths"]
            for edge in path["edges"]
            for evidence_id in edge["evidence_event_ids"]
        })
        evidence_events = (
            self.store.get_events(selected_evidence_ids)
            if selected_evidence_ids else {}
        )

        paths = []
        for path in search["paths"]:
            node_records = []
            for event_id in path["node_ids"]:
                event = events_by_id[event_id]
                node_records.append({
                    "event_id": event_id,
                    "event_type": event["event_type"],
                    "created_at": event["created_at"],
                })
            relation_records = []
            for edge in path["edges"]:
                available_evidence = [
                    event_id for event_id in edge["evidence_event_ids"]
                    if (
                        event_id in evidence_events
                        and evidence_events[event_id].get("event_type")
                        not in self.GRAPH_EVENT_TYPES
                    )
                ]
                missing_evidence = sorted(
                    set(edge["evidence_event_ids"]) - set(available_evidence)
                )
                relation_records.append({
                    "relation_event_id": edge["relation_event_id"],
                    "subject_event_id": edge["subject_event_id"],
                    "object_event_id": edge["object_event_id"],
                    "predicate": edge["predicate"],
                    "traversal_direction": edge["traversal_direction"],
                    "evidence_event_ids": available_evidence,
                    "missing_evidence_event_ids": missing_evidence,
                    "created_at": edge["created_at"],
                    "epistemic_state": "candidate_unverified",
                    "verified": False,
                })
            paths.append({
                "node_event_ids": path["node_ids"],
                "nodes": node_records,
                "relations": relation_records,
                "hops": len(relation_records),
                "epistemic_state": "candidate_unverified",
                "verified": False,
                "causal_attribution": "not_established",
            })

        return {
            "status": "bounded" if search["search_may_be_truncated"] else "completed",
            "source_event_id": source,
            "target_event_id": target,
            "direction": direction,
            "predicate_filter": predicate,
            "path_count": len(paths),
            "paths": paths,
            "candidate_edge_count": usable_edge_count,
            "edge_visits": search["edge_visits"],
            "max_hops": max_hops,
            "max_paths": max_paths,
            "max_edge_visits": max_edge_visits,
            "history_window_limit": history_limit,
            "history_may_be_incomplete": len(relation_events) == history_limit,
            "search_may_be_truncated": search["search_may_be_truncated"],
            "persistent_write_performed": False,
            "all_paths_unverified": True,
            "causal_attribution": "not_established",
        }

    def list_interpretations(
        self, source_event_id: int, *, limit: int = 200
    ) -> dict[str, Any]:
        source = self._event_id(source_event_id, "source_event_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_RECORDS:
            raise MemoryGraphError(f"limit deve ser inteiro entre 1 e {self.MAX_RECORDS}.")
        self._require_source_event(source, "source_event_id")
        events = self.store.list_events(
            limit=limit, event_type=self.INTERPRETATION_EVENT_TYPE
        )
        records = []
        for event in reversed(events):
            payload = event.get("payload", {})
            if isinstance(payload, dict) and payload.get("source_event_id") == source:
                records.append({
                    "event_id": event["id"],
                    **payload,
                    "verified": False,
                })
        return {
            "status": "completed",
            "source_event_id": source,
            "interpretations": records,
            "count": len(records),
            "history_window_limit": limit,
            "history_may_be_incomplete": len(events) == limit,
            "source_event_mutated": False,
        }

    def status(self) -> dict[str, Any]:
        relation_count = self.store.count_events(self.RELATION_EVENT_TYPE)
        interpretation_count = self.store.count_events(self.INTERPRETATION_EVENT_TYPE)
        return {
            "component": "MemoryGraphEngine",
            "version": self.VERSION,
            "storage": "canonical_knowledge_store_events",
            "relation_candidate_count": relation_count,
            "interpretation_count": interpretation_count,
            "chunk_anchor_count": self.store.count_events(self.CHUNK_ANCHOR_EVENT_TYPE),
            "maximum_history_window": self.MAX_RECORDS,
            "history_may_be_incomplete": False,
            "all_new_relations_unverified": True,
            "all_interpretations_unverified": True,
            "source_events_mutated": False,
            "new_database_or_tables": False,
            "semantic_promotion_automatic": False,
            "path_tracing_supported": True,
            "path_tracing_read_only": True,
            "path_tracing_epistemic_state": "candidate_unverified",
            "path_tracing_max_hops": 6,
            "path_tracing_max_paths": 20,
            "path_tracing_max_edge_visits": 5000,
        }
