"""One-step coordinator joining exploration planning to evolution governance.

This module admits candidate records into a bounded lifecycle. It does not
create workspaces, execute candidate code, persist memory, or promote changes.
"""
from __future__ import annotations

import math
import re
from typing import Any, Sequence

from experiments.cognitive_exploration_cycle import (
    CognitiveExplorationCycle,
    CognitiveExplorationCycleError,
)
from experiments.digital_physiology import DigitalPhysiologyState, ResourceObservation
from experiments.cognitive_interest_selector import InterestBudget
from experiments.evolution_governor import (
    CandidateStage,
    EvolutionGovernanceError,
    EvolutionGovernor,
)


class AutonomousLabCycleError(ValueError):
    """Invalid lab-cycle envelope or planning input."""


class AutonomousLabCycle:
    """Plan and admit the next bounded experiment from a supplied backlog."""

    VERSION = "0.1.0"
    _GOVERNANCE_KEYS = {
        "parent_digest", "change_scope", "risk_class", "estimated_test_evaluations",
        "external_effects", "protected_target",
    }

    def __init__(
        self,
        *,
        planner: CognitiveExplorationCycle | None = None,
        governor: EvolutionGovernor | None = None,
    ) -> None:
        self.planner = planner or CognitiveExplorationCycle()
        self.governor = governor or EvolutionGovernor()

    @staticmethod
    def _cycle_id(value: Any) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value
        ):
            raise AutonomousLabCycleError("cycle_id inválido.")
        return value

    @classmethod
    def _parse_backlog(
        cls, candidates: Sequence[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        if not isinstance(candidates, (list, tuple)) or len(candidates) > 256:
            raise AutonomousLabCycleError("backlog inválido ou acima do limite.")
        interests: list[dict[str, Any]] = []
        metadata: dict[str, dict[str, Any]] = {}
        for index, envelope in enumerate(candidates):
            if not isinstance(envelope, dict) or set(envelope) != {"interest", "governance"}:
                raise AutonomousLabCycleError(f"backlog[{index}] deve conter interest e governance.")
            interest, governance = envelope["interest"], envelope["governance"]
            if not isinstance(interest, dict) or not isinstance(governance, dict):
                raise AutonomousLabCycleError(f"backlog[{index}] contém envelope inválido.")
            candidate_id = interest.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise AutonomousLabCycleError(f"backlog[{index}] sem candidate_id.")
            if candidate_id in metadata:
                raise AutonomousLabCycleError("candidate_id duplicado no backlog.")
            if not cls._GOVERNANCE_KEYS.issuperset(governance):
                raise AutonomousLabCycleError(f"backlog[{index}] contém campos de governança desconhecidos.")
            if not cls._GOVERNANCE_KEYS.issubset(governance):
                raise AutonomousLabCycleError(f"backlog[{index}] sem metadados de governança.")
            metadata[candidate_id] = governance
            interests.append(interest)
        return interests, metadata

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
        cycle_id = self._cycle_id(cycle_id)
        interests, metadata = self._parse_backlog(backlog)
        try:
            plan = self.planner.plan(
                state=state,
                observation=observation,
                candidates=interests,
                base_budget=base_budget,
                minimum_score=minimum_score,
            )
        except CognitiveExplorationCycleError as exc:
            raise AutonomousLabCycleError(str(exc)) from exc

        admitted: list[str] = []
        blocked: list[dict[str, str]] = []
        selection = plan.get("selection")
        selected_order = selection.get("selected_order", []) if isinstance(selection, dict) else []

        for candidate_id in selected_order:
            governance = metadata[candidate_id]
            if governance["risk_class"] in {"high", "critical"}:
                blocked.append({
                    "candidate_id": candidate_id,
                    "reason": "high_risk_requires_separate_review",
                })
                continue
            interest = next(item for item in interests if item["candidate_id"] == candidate_id)
            try:
                runtime_ms = interest["estimated_runtime_ms"]
                if isinstance(runtime_ms, bool) or not isinstance(runtime_ms, int) or runtime_ms < 0:
                    raise EvolutionGovernanceError("estimated_runtime_ms inválido.")
                self.governor.register(
                    candidate_id=candidate_id,
                    parent_digest=governance["parent_digest"],
                    change_scope=governance["change_scope"],
                    risk_class=governance["risk_class"],
                    estimated_runtime_seconds=math.ceil(runtime_ms / 1000),
                    estimated_memory_mb=interest["estimated_ram_mb"],
                    estimated_test_evaluations=governance["estimated_test_evaluations"],
                    external_effects=governance["external_effects"],
                    protected_target=governance["protected_target"],
                )
                self.governor.transition(
                    candidate_id,
                    CandidateStage.TRIAGED,
                    evidence_ref=f"admission:{cycle_id}",
                )
                admitted.append(candidate_id)
            except (EvolutionGovernanceError, KeyError, TypeError, ValueError) as exc:
                blocked.append({"candidate_id": candidate_id, "reason": str(exc)})

        if admitted and blocked:
            status = "partially_admitted"
        elif admitted:
            status = "admitted"
        elif selected_order:
            status = "blocked"
        else:
            status = plan["status"]

        return {
            "schema": "mahoraga.autonomous_lab_cycle",
            "schema_version": 1,
            "cycle_version": self.VERSION,
            "cycle_id": cycle_id,
            "status": status,
            "planning": plan,
            "admitted_candidate_ids": admitted,
            "blocked_candidates": blocked,
            "governor": self.governor.snapshot(),
            "candidate_discovery_performed": False,
            "workspace_created": False,
            "candidate_code_executed": False,
            "memory_persisted": False,
            "production_modified": False,
            "automatic_promotion": False,
        }
