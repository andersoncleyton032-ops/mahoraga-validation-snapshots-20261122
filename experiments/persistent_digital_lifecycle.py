"""Persistent, versioned physiology cycles for the Mahoraga research runtime.

This layer persists state transitions in the canonical KnowledgeStore event
stream. It does not create a second database, read device sensors, schedule
work, execute tasks, or grant permissions. Callers must provide observations;
their provenance is retained as caller-reported or simulated.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from agent.store import EventSequenceConflict
from experiments.digital_physiology import (
    DigitalHomeostasis,
    DigitalPhysiologyError,
    DigitalPhysiologyState,
    ResourceObservation,
)


class ContinuousLifecycleError(ValueError):
    """Invalid persisted lifecycle state or transition."""


class ContinuousLifecycleConflict(ContinuousLifecycleError):
    """A lifecycle transition was based on a stale state version."""


class PersistentDigitalLifecycle:
    """Recover and atomically advance a persistent digital-physiology state."""

    VERSION = "0.2.0"
    SCHEMA_VERSION = 2
    EVENT_TYPE = "digital.lifecycle.snapshot"
    SEQUENCE_KEY = "digital.lifecycle.snapshot"
    SCHEMA = "mahoraga.digital_lifecycle_snapshot"

    def __init__(self, store, homeostasis: DigitalHomeostasis | None = None):
        if store is None or not callable(getattr(store, "list_events", None)):
            raise ContinuousLifecycleError("store precisa ser um KnowledgeStore compatível.")
        if not callable(getattr(store, "record_versioned_event", None)):
            raise ContinuousLifecycleError("store não oferece append versionado atômico.")
        if homeostasis is not None and not isinstance(homeostasis, DigitalHomeostasis):
            raise ContinuousLifecycleError("homeostasis precisa ser DigitalHomeostasis.")
        self.store = store
        self.homeostasis = homeostasis or DigitalHomeostasis()

    def _homeostasis_snapshot(self) -> dict[str, Any]:
        body = {
            "engine_version": self.homeostasis.VERSION,
            "config": asdict(self.homeostasis.config),
        }
        canonical = json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return {
            **body,
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _initial_state() -> dict[str, Any]:
        state = DigitalPhysiologyState()
        return {
            "cycle": state.cycle,
            "energy_reserve": state.energy_reserve,
            "thermal_load": state.thermal_load,
            "memory_pressure": state.memory_pressure,
            "cognitive_load": state.cognitive_load,
            "recovery_reserve": state.recovery_reserve,
            "control_state": state.control_state,
        }

    def _latest(self) -> dict[str, Any]:
        events = self.store.list_events(limit=1, event_type=self.EVENT_TYPE)
        if not events:
            return {
                "version": 0,
                "event_id": None,
                "state": self._initial_state(),
                "persisted": False,
                "snapshot": None,
            }

        event = events[0]
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("schema") != self.SCHEMA:
            raise ContinuousLifecycleError("Snapshot persistido possui esquema inválido.")
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ContinuousLifecycleError("Versão de esquema do lifecycle não suportada.")
        if payload.get("lifecycle_version") != self.VERSION:
            raise ContinuousLifecycleError("Versão do lifecycle persistido não corresponde.")
        if payload.get("homeostasis") != self._homeostasis_snapshot():
            raise ContinuousLifecycleError(
                "Configuração de homeostase diverge do snapshot persistido; recuperação bloqueada."
            )
        version = payload.get("version")
        state = payload.get("state")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ContinuousLifecycleError("Versão persistida inválida.")
        if not isinstance(state, dict):
            raise ContinuousLifecycleError("Estado fisiológico persistido inválido.")
        try:
            validated = DigitalPhysiologyState(**state)
        except (TypeError, DigitalPhysiologyError) as exc:
            raise ContinuousLifecycleError("Estado fisiológico persistido não é válido.") from exc
        if validated.cycle != version:
            raise ContinuousLifecycleError(
                "Versão do snapshot diverge do ciclo fisiológico; recuperação bloqueada."
            )
        normalized_state = {
            "cycle": validated.cycle,
            "energy_reserve": validated.energy_reserve,
            "thermal_load": validated.thermal_load,
            "memory_pressure": validated.memory_pressure,
            "cognitive_load": validated.cognitive_load,
            "recovery_reserve": validated.recovery_reserve,
            "control_state": validated.control_state,
        }
        return {
            "version": version,
            "event_id": event.get("id"),
            "state": normalized_state,
            "persisted": True,
            "snapshot": payload,
        }

    def recover(self) -> dict[str, Any]:
        """Recover the latest committed state, or return an explicit baseline."""
        latest = self._latest()
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "lifecycle_version": self.VERSION,
            "version": latest["version"],
            "event_id": latest["event_id"],
            "state": dict(latest["state"]),
            "homeostasis_config_sha256": self._homeostasis_snapshot()["sha256"],
            "persisted": latest["persisted"],
            "state_origin": (
                "persisted_snapshot"
                if latest["persisted"] else "default_initial_condition"
            ),
            "recovered": True,
            "authorization_granted": False,
            "work_dispatched": False,
        }

    def advance(
        self,
        observation: ResourceObservation,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Apply one supplied observation and commit exactly one state version."""
        if not isinstance(observation, ResourceObservation):
            raise ContinuousLifecycleError("observation precisa ser ResourceObservation.")
        if expected_version is not None and (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 0
        ):
            raise ContinuousLifecycleError("expected_version deve ser inteiro não negativo.")

        latest = self._latest()
        base_version = latest["version"]
        if expected_version is not None and expected_version != base_version:
            raise ContinuousLifecycleConflict(
                f"Versão obsoleta: esperada {expected_version}, atual {base_version}."
            )

        try:
            physiology = self.homeostasis.update(
                DigitalPhysiologyState(**latest["state"]), observation
            )
        except DigitalPhysiologyError as exc:
            raise ContinuousLifecycleError(str(exc)) from exc

        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        payload = {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "lifecycle_version": self.VERSION,
            "homeostasis": self._homeostasis_snapshot(),
            "previous_event_id": latest["event_id"],
            "state": physiology["state"],
            "regulation": physiology["regulation"],
            "observation": {
                "values": {
                    name: getattr(observation, name)
                    for name in (
                        "cpu_load", "memory_pressure", "thermal_pressure",
                        "energy_drain", "cooling", "recharge", "task_load",
                        "unresolved_uncertainty", "expected_learning_progress",
                        "noise_risk",
                    )
                },
                "source": observation.source,
                "epistemic_state": (
                    "caller_reported" if observation.source == "caller_observed"
                    else "simulated"
                ),
                "authenticated": False,
                "captured_at": now,
            },
            "effects": {
                "hardware_read": False,
                "memory_payload_duplicated": False,
                "work_dispatched": False,
                "authorization_granted": False,
                "governor_called": False,
            },
        }
        try:
            committed = self.store.record_versioned_event(
                self.EVENT_TYPE,
                self.SEQUENCE_KEY,
                base_version,
                payload,
                sequence_field="version",
            )
        except EventSequenceConflict as exc:
            raise ContinuousLifecycleConflict(str(exc)) from exc

        payload["version"] = committed["sequence"]
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "lifecycle_version": self.VERSION,
            "version": committed["sequence"],
            "event_id": committed["event_id"],
            "state": physiology["state"],
            "regulation": physiology["regulation"],
            "homeostasis_config_sha256": payload["homeostasis"]["sha256"],
            "observation_provenance": payload["observation"],
            "persisted": True,
            "recovered": False,
            "authorization_granted": False,
            "work_dispatched": False,
        }
