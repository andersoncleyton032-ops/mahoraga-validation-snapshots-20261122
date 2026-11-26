"""Append-only persistence adapter for redacted cognitive cycle continuity."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .cognitive_fabric import CognitiveWorkspace, CognitiveFabricError
from .store import EventSequenceConflict


class CognitiveContinuityConflict(RuntimeError):
    """A cycle identifier was reused for a different terminal record."""


class CognitiveContinuityLedger:
    """Persist one terminal summary per workspace in the canonical KnowledgeStore."""

    VERSION = "0.1.0"
    EVENT_TYPE = "introspection.cognitive_cycle.completed"
    SEQUENCE_PREFIX = "cognitive_cycle:"
    MAX_RECENT_CYCLES = 100

    def __init__(self, store):
        if store is None or not callable(getattr(store, "record_versioned_event", None)):
            raise CognitiveFabricError("KnowledgeStore compatível é obrigatório.")
        if not callable(getattr(store, "find_events_by_payload_value", None)):
            raise CognitiveFabricError("KnowledgeStore precisa oferecer busca idempotente.")
        if not callable(getattr(store, "list_events", None)):
            raise CognitiveFabricError("KnowledgeStore precisa oferecer leitura de eventos.")
        self.store = store

    @staticmethod
    def _fingerprint(record: dict[str, Any]) -> str:
        stable = json.loads(json.dumps(record, ensure_ascii=False, sort_keys=True))
        stable["cycle"].pop("completed_at", None)
        canonical = json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record_terminal_cycle(
        self,
        workspace: CognitiveWorkspace,
        outcome: str,
        *,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(workspace, CognitiveWorkspace):
            raise CognitiveFabricError("workspace precisa ser CognitiveWorkspace.")
        record = workspace.continuity_record(
            outcome,
            completed_at=completed_at,
        )
        correlation_id = record["cycle"]["correlation_id"]
        fingerprint = self._fingerprint(record)
        payload = {
            "schema": "mahoraga.cognitive_continuity_event",
            "schema_version": 1,
            "correlation_id": correlation_id,
            "cycle_fingerprint": fingerprint,
            "record": record,
        }
        sequence_key = self.SEQUENCE_PREFIX + correlation_id

        try:
            saved = self.store.record_versioned_event(
                self.EVENT_TYPE,
                sequence_key,
                expected_sequence=0,
                payload=payload,
                sequence_field="cycle_sequence",
            )
            return {
                "status": "recorded",
                "event_id": saved["event_id"],
                "cycle_sequence": saved["sequence"],
                "correlation_id": correlation_id,
                "cycle_fingerprint": fingerprint,
                "duplicate": False,
                "persistence": "canonical_knowledge_store",
            }
        except EventSequenceConflict as exc:
            existing = self.store.find_events_by_payload_value(
                self.EVENT_TYPE,
                "correlation_id",
                correlation_id,
                limit=2,
            )
            if len(existing) != 1:
                raise CognitiveContinuityConflict(
                    "Conflito de sequência sem um evento canônico único."
                ) from exc
            prior = existing[0]
            prior_payload = prior.get("payload", {})
            if (
                prior_payload.get("schema") != "mahoraga.cognitive_continuity_event"
                or prior_payload.get("schema_version") != 1
                or prior_payload.get("cycle_fingerprint") != fingerprint
            ):
                raise CognitiveContinuityConflict(
                    "O mesmo ciclo foi reapresentado com conteúdo terminal diferente."
                ) from exc
            return {
                "status": "already_recorded",
                "event_id": prior["id"],
                "cycle_sequence": prior_payload.get("cycle_sequence"),
                "correlation_id": correlation_id,
                "cycle_fingerprint": fingerprint,
                "duplicate": True,
                "persistence": "canonical_knowledge_store",
            }

    def recent_cycles(self, limit: int = 20) -> list[dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self.MAX_RECENT_CYCLES
        ):
            raise ValueError(
                f"limit deve ser inteiro entre 1 e {self.MAX_RECENT_CYCLES}."
            )
        events = self.store.list_events(
            limit=limit,
            event_type=self.EVENT_TYPE,
        )
        result = []
        for event in reversed(events):
            payload = event.get("payload", {})
            record = payload.get("record")
            if (
                payload.get("schema") != "mahoraga.cognitive_continuity_event"
                or payload.get("schema_version") != 1
                or not isinstance(record, dict)
                or record.get("schema") != "mahoraga.cognitive_continuity_record"
                or record.get("schema_version") != 1
            ):
                continue
            result.append({
                "event_id": event["id"],
                "cycle_sequence": payload.get("cycle_sequence"),
                "cycle_fingerprint": payload.get("cycle_fingerprint"),
                "record": record,
            })
        return result

    def snapshot(self, limit: int = 20) -> dict[str, Any]:
        """Return a bounded, redacted history summary for the operational self-model."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit deve ser inteiro entre 1 e 20.")
        recent = self.recent_cycles(limit=min(limit + 1, self.MAX_RECENT_CYCLES))
        truncated = len(recent) > limit
        selected = recent[-limit:]
        outcomes: dict[str, int] = {}
        summaries = []
        for item in selected:
            record = item["record"]
            outcome = record["outcome"]
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            cycle = record["cycle"]
            focus = record["focus"]
            summaries.append({
                "event_id": item["event_id"],
                "cycle_sequence": item["cycle_sequence"],
                "correlation_id": cycle["correlation_id"],
                "outcome": outcome,
                "completed_at": cycle["completed_at"],
                "last_signal_topic": focus["last_signal_topic"],
                "topics_observed": list(focus["topics_observed"][:16]),
                "topics_truncated": len(focus["topics_observed"]) > 16,
                "participating_components": list(focus["participating_components"][:16]),
                "components_truncated": len(focus["participating_components"]) > 16,
                "signal_count": cycle["signal_count"],
                "stage_count": cycle["stage_count"],
            })
        return {
            "status": "available" if summaries else "empty",
            "persistence": "canonical_knowledge_store",
            "cycle_count": len(summaries),
            "window_limit": limit,
            "truncated": truncated,
            "outcomes": dict(sorted(outcomes.items())),
            "recent_cycles": summaries,
            "latest_cycle": summaries[-1] if summaries else None,
            "raw_request_text_included": False,
            "signal_payloads_included": False,
            "subjective_experience_status": "unknown_not_inferred",
            "causal_attribution": "not_established",
        }

    def status(self) -> dict[str, Any]:
        return {
            "component": "CognitiveContinuityLedger",
            "version": self.VERSION,
            "event_type": self.EVENT_TYPE,
            "persistence": "canonical_knowledge_store",
            "append_only": True,
            "per_cycle_idempotency": "versioned_event_sequence",
            "max_recent_cycles": self.MAX_RECENT_CYCLES,
            "raw_request_text_persisted": False,
            "signal_payloads_persisted": False,
            "artifact_values_persisted": False,
            "subjective_experience_claim": False,
        }
