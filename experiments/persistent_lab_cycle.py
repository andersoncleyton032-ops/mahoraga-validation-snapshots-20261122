"""Persistent one-cycle lab orchestration with replay-safe experiment records.

This wrapper persists planning/admission decisions in KnowledgeStore. It does
not discover candidates, generate patches, execute code, or run in background.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence

from agent.store import KnowledgeStore
from experiments.autonomous_lab_cycle import AutonomousLabCycle
from experiments.digital_physiology import DigitalPhysiologyState, ResourceObservation
from experiments.cognitive_interest_selector import InterestBudget


class PersistentAutonomousLabCycleError(RuntimeError):
    """A cycle result could not be safely persisted or replayed."""


class PersistentAutonomousLabCycle:
    VERSION = "0.1.0"

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        cycle_factory=AutonomousLabCycle,
    ) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store precisa ser uma KnowledgeStore.")
        if not callable(cycle_factory):
            raise TypeError("cycle_factory precisa ser chamável.")
        self.store = store
        self.cycle_factory = cycle_factory

    @staticmethod
    def _experiment_id(cycle_id: str, candidate_id: str) -> str:
        raw = f"{cycle_id}\0{candidate_id}".encode("utf-8")
        return "lab-" + hashlib.sha256(raw).hexdigest()[:48]

    @staticmethod
    def _valid_digest(value: Any) -> str | None:
        if (
            isinstance(value, str) and len(value) == 64
            and re.fullmatch(r"[0-9a-f]{64}", value)
        ):
            return value
        return None

    def run_cycle(
        self,
        *,
        cycle_id: str,
        state: DigitalPhysiologyState,
        observation: ResourceObservation,
        backlog: Sequence[dict[str, Any]],
        base_budget: InterestBudget,
        minimum_score: float = 0.05,
    ) -> dict[str, Any]:
        cycle = self.cycle_factory()
        result = cycle.run_cycle(
            cycle_id=cycle_id,
            state=state,
            observation=observation,
            backlog=backlog,
            base_budget=base_budget,
            minimum_score=minimum_score,
        )
        admitted = set(result["admitted_candidate_ids"])
        blocked = {
            item["candidate_id"]: item["reason"]
            for item in result["blocked_candidates"]
        }
        selection = result.get("planning", {}).get("selection", {})
        selected = set(selection.get("selected_order", []))
        records = []
        created_count = 0
        replayed_count = 0

        for envelope in backlog:
            interest = envelope["interest"]
            governance = envelope["governance"]
            candidate_id = interest["candidate_id"]
            if candidate_id in admitted:
                decision = {"status": "admitted", "reason": "bounded_admission"}
            elif candidate_id in blocked:
                decision = {"status": "blocked", "reason": blocked[candidate_id]}
            elif candidate_id in selected:
                decision = {"status": "selected_not_admitted", "reason": "not_admitted"}
            else:
                decision = {"status": "not_selected", "reason": "below_selection_or_budget"}

            payload = {
                "schema": "mahoraga.lab_candidate_record",
                "schema_version": 1,
                "cycle_id": cycle_id,
                "candidate_id": candidate_id,
                "interest": interest,
                "governance": governance,
                "decision": decision,
                "cycle_version": result["cycle_version"],
            }
            experiment_id = self._experiment_id(cycle_id, candidate_id)
            parent_digest = self._valid_digest(governance.get("parent_digest"))
            try:
                persisted = self.store.create_lab_experiment_once(
                    experiment_id, payload, parent_digest=parent_digest,
                )
                record = persisted["record"]
                if persisted["created"]:
                    created_count += 1
                else:
                    replayed_count += 1

                if decision["status"] == "admitted":
                    if record["stage"] == "proposed":
                        record = self.store.transition_lab_experiment(
                            experiment_id,
                            expected_version=record["version"],
                            expected_stage="proposed",
                            new_stage="triaged",
                            evidence={
                                "cycle_id": cycle_id,
                                "decision": "admitted",
                                "source": "PersistentAutonomousLabCycle",
                            },
                        )
                    elif record["stage"] != "triaged":
                        raise PersistentAutonomousLabCycleError(
                            "Registro existente está em estado incompatível com a admissão."
                        )
                elif record["stage"] != "proposed":
                    raise PersistentAutonomousLabCycleError(
                        "Registro não admitido já avançou além de proposed."
                    )
                records.append({
                    "candidate_id": candidate_id,
                    "experiment_id": experiment_id,
                    "decision": decision["status"],
                    "stage": record["stage"],
                })
            except (ValueError, KeyError, TypeError) as exc:
                raise PersistentAutonomousLabCycleError(
                    f"Falha ao persistir candidato {candidate_id}: {exc}"
                ) from exc

        result["experiment_ledger"] = {
            "schema": "mahoraga.persistent_lab_cycle",
            "version": self.VERSION,
            "records": records,
            "created": created_count,
            "replayed": replayed_count,
            "audit": self.store.audit_lab_experiments(),
        }
        result["experiment_records_persisted"] = True
        return result
