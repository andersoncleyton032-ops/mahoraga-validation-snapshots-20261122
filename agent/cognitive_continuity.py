"""Append-only persistence adapter for redacted cognitive cycle continuity."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .cognitive_fabric import CognitiveWorkspace, CognitiveFabricError


class CognitiveContinuityConflict(RuntimeError):
    """A cycle identifier was reused for a different terminal record."""


class CognitiveContinuityLedger:
    """Persist one terminal summary per workspace in the canonical KnowledgeStore."""

    VERSION = "0.1.0"
    EVENT_TYPE = "introspection.cognitive_cycle.completed"
    IDEMPOTENCY_PREFIX = "cognitive_cycle:"
    MAX_RECENT_CYCLES = 100

    def __init__(self, store):
        if store is None or not callable(getattr(store, "record_event_once", None)):
            raise CognitiveFabricError("KnowledgeStore precisa oferecer record_event_once.")
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
    ) -> dict[str, Any]:
        if not isinstance(workspace, CognitiveWorkspace):
            raise CognitiveFabricError("workspace precisa ser CognitiveWorkspace.")
        # The event row's created_at is the authoritative terminal timestamp.
        # Keeping it outside the payload makes retries byte-identical.
        record = workspace.continuity_record(outcome)
        correlation_id = record["cycle"]["correlation_id"]
        fingerprint = self._fingerprint(record)
        payload = {
            "schema": "mahoraga.cognitive_continuity_event",
            "schema_version": 1,
            "correlation_id": correlation_id,
            "cycle_fingerprint": fingerprint,
            "record": record,
        }
        idempotency_key = self.IDEMPOTENCY_PREFIX + correlation_id
        try:
            saved = self.store.record_event_once(
                self.EVENT_TYPE,
                idempotency_key,
                payload=payload,
            )
        except ValueError as exc:
            raise CognitiveContinuityConflict(
                "O mesmo ciclo foi reapresentado com conteúdo terminal diferente."
            ) from exc
        created = saved["created"] is True
        return {
            "status": "recorded" if created else "already_recorded",
            "event_id": saved["event_id"],
            "cycle_sequence": saved["event_id"],
            "correlation_id": correlation_id,
            "cycle_fingerprint": fingerprint,
            "duplicate": not created,
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
                or record.get("outcome") not in {"completed", "deferred", "failed", "cancelled"}
                or not isinstance(record.get("cycle"), dict)
                or not isinstance(record.get("focus"), dict)
                or record["cycle"].get("correlation_id") != payload.get("correlation_id")
                or not isinstance(event.get("created_at"), str)
            ):
                continue
            try:
                fingerprint = self._fingerprint(record)
            except (TypeError, ValueError, OverflowError):
                continue
            if payload.get("cycle_fingerprint") != fingerprint:
                continue
            restored_record = json.loads(json.dumps(record, ensure_ascii=False))
            restored_record["cycle"]["completed_at"] = event["created_at"]
            result.append({
                "event_id": event["id"],
                "cycle_sequence": event["id"],
                "cycle_fingerprint": fingerprint,
                "record": restored_record,
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
            "idempotency": "KnowledgeStore.record_event_once",
            "idempotency_key": "per_correlation_id",
            "max_recent_cycles": self.MAX_RECENT_CYCLES,
            "raw_request_text_persisted": False,
            "signal_payloads_persisted": False,
            "artifact_values_persisted": False,
            "subjective_experience_claim": False,
        }
