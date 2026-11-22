"""Experimental coupling of homeostatic state and cognitive exploration.

This adapter coordinates two research primitives. It consumes candidate
investigations already proposed by a caller, applies a homeostatic resource
gate, then invokes the bounded interest selector. It does not discover
interests, create executive goals, persist memory, or execute work.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from experiments.cognitive_interest_selector import (
    CognitiveInterestSelector,
    InterestBudget,
    InterestSelectionError,
)
from experiments.digital_physiology import (
    DigitalHomeostasis,
    DigitalPhysiologyError,
    DigitalPhysiologyState,
    ResourceObservation,
)


class CognitiveExplorationCycleError(ValueError):
    """Invalid exploration-cycle input or coordination contract."""


class CognitiveExplorationCycle:
    VERSION = "0.1.0"

    def __init__(
        self,
        selector: CognitiveInterestSelector | None = None,
        homeostasis: DigitalHomeostasis | None = None,
    ):
        self.selector = selector or CognitiveInterestSelector()
        self.homeostasis = homeostasis or DigitalHomeostasis()

    def plan(
        self,
        *,
        state: DigitalPhysiologyState,
        observation: ResourceObservation,
        candidates: Sequence[dict[str, Any]],
        base_budget: InterestBudget,
        minimum_score: float = 0.05,
    ) -> dict[str, Any]:
        """Return an advisory plan whose exploration budget follows physiology."""
        if not isinstance(state, DigitalPhysiologyState):
            raise CognitiveExplorationCycleError("state inválido.")
        if not isinstance(observation, ResourceObservation):
            raise CognitiveExplorationCycleError("observation inválida.")
        if not isinstance(base_budget, InterestBudget):
            raise CognitiveExplorationCycleError("base_budget inválido.")
        if not isinstance(candidates, (list, tuple)):
            raise CognitiveExplorationCycleError("candidates deve ser lista ou tupla.")
        if isinstance(minimum_score, bool) or not isinstance(minimum_score, (int, float)):
            raise CognitiveExplorationCycleError("minimum_score inválido.")
        try:
            minimum_score = float(minimum_score)
        except (OverflowError, TypeError, ValueError) as exc:
            raise CognitiveExplorationCycleError("minimum_score inválido.") from exc
        if not math.isfinite(minimum_score) or not 0.0 <= minimum_score <= 1.0:
            raise CognitiveExplorationCycleError("minimum_score inválido.")

        try:
            physiology = self.homeostasis.update(state, observation)
        except DigitalPhysiologyError as exc:
            raise CognitiveExplorationCycleError(str(exc)) from exc

        control = physiology["state"]["control_state"]
        admission_factor = physiology["regulation"]["recommended_admission_factor"]
        exploration_factor = physiology["regulation"]["exploration_budget"]
        # exploration_budget already incorporates admission, resource capacity,
        # unresolved uncertainty, expected learning progress and noise risk.
        # Use it as the effective exploration allocation, not merely as telemetry.
        factor = exploration_factor
        if control == "pause" or factor <= 0.0:
            return {
                "schema": "mahoraga.cognitive_exploration_plan",
                "schema_version": 1,
                "cycle_version": self.VERSION,
                "status": "deferred",
                "reason": "homeostatic_pause",
                "physiology": physiology,
                "effective_exploration_factor": factor,
                "selection": None,
                "candidate_discovery_performed": False,
                "memory_persisted": False,
                "goal_created": False,
                "work_executed": False,
                "authorization_granted": False,
            }

        scaled_runtime = int(base_budget.max_runtime_ms * factor)
        scaled_ram = int(base_budget.max_ram_mb * factor)
        scaled_selected = max(1, int(base_budget.max_selected * factor))
        if scaled_runtime < 1 or scaled_ram < 1:
            return {
                "schema": "mahoraga.cognitive_exploration_plan",
                "schema_version": 1,
                "cycle_version": self.VERSION,
                "status": "deferred",
                "reason": "insufficient_admission_budget",
                "physiology": physiology,
                "selection": None,
                "candidate_discovery_performed": False,
                "memory_persisted": False,
                "goal_created": False,
                "work_executed": False,
                "authorization_granted": False,
            }

        # When physiological reserve is reduced, require more expected utility
        # per candidate rather than merely trying fewer low-value tasks.
        adjusted_minimum = min(
            1.0, float(minimum_score) + (1.0 - factor) * 0.20
        )
        budget = InterestBudget(
            max_runtime_ms=scaled_runtime,
            max_ram_mb=scaled_ram,
            max_selected=min(base_budget.max_selected, scaled_selected),
        )
        try:
            selection = self.selector.select(
                candidates, budget, minimum_score=adjusted_minimum
            )
        except InterestSelectionError as exc:
            raise CognitiveExplorationCycleError(str(exc)) from exc

        return {
            "schema": "mahoraga.cognitive_exploration_plan",
            "schema_version": 1,
            "cycle_version": self.VERSION,
            "status": selection["status"],
            "reason": "homeostasis_adjusted_candidate_selection",
            "physiology": physiology,
            "effective_exploration_factor": factor,
            "selection": selection,
            "candidate_discovery_performed": False,
            "memory_persisted": False,
            "goal_created": False,
            "work_executed": False,
            "authorization_granted": False,
        }
