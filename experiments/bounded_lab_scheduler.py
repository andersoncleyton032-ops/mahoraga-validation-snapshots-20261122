"""Bounded batch scheduler for persistent lab planning cycles.

All resource values are caller-supplied estimates or observations. This module
does not read Android sensors, sleep, start background workers, execute code,
or claim measured runtime/energy consumption.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from experiments.cognitive_interest_selector import InterestBudget
from experiments.digital_physiology import DigitalPhysiologyState, ResourceObservation
from experiments.persistent_lab_cycle import PersistentAutonomousLabCycle


class LabSchedulerError(ValueError):
    """Invalid scheduler policy, round request, or resource envelope."""


@dataclass(frozen=True)
class LabSchedulerPolicy:
    max_rounds: int = 8
    max_total_runtime_ms: int = 60_000
    max_peak_memory_mb: int = 256
    max_total_test_evaluations: int = 10_000
    max_cpu_load: float = 0.85
    max_memory_pressure: float = 0.80
    max_thermal_pressure: float = 0.75
    max_energy_drain: float = 0.75

    def __post_init__(self) -> None:
        for name, value, upper in (
            ("max_rounds", self.max_rounds, 16),
            ("max_total_runtime_ms", self.max_total_runtime_ms, 600_000),
            ("max_peak_memory_mb", self.max_peak_memory_mb, 4096),
            ("max_total_test_evaluations", self.max_total_test_evaluations, 1_000_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
                raise LabSchedulerError(f"{name} fora dos limites permitidos.")
        for name, value in (
            ("max_cpu_load", self.max_cpu_load),
            ("max_memory_pressure", self.max_memory_pressure),
            ("max_thermal_pressure", self.max_thermal_pressure),
            ("max_energy_drain", self.max_energy_drain),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise LabSchedulerError(f"{name} precisa estar entre 0 e 1.")


class BoundedLabScheduler:
    VERSION = "0.1.0"
    _ROUND_KEYS = {
        "cycle_id", "state", "observation", "backlog", "base_budget",
        "estimated_runtime_ms", "estimated_memory_mb",
        "estimated_test_evaluations",
    }

    def __init__(
        self,
        persistent_cycle: PersistentAutonomousLabCycle,
        policy: LabSchedulerPolicy | None = None,
    ) -> None:
        if not isinstance(persistent_cycle, PersistentAutonomousLabCycle):
            raise TypeError("persistent_cycle precisa ser PersistentAutonomousLabCycle.")
        self.persistent_cycle = persistent_cycle
        self.policy = policy or LabSchedulerPolicy()

    def _validate_rounds(self, rounds: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(rounds, (list, tuple)) or len(rounds) > self.policy.max_rounds:
            raise LabSchedulerError("Quantidade de rodadas inválida ou acima do limite.")
        normalized = []
        seen = set()
        for index, item in enumerate(rounds):
            if not isinstance(item, dict) or set(item) != self._ROUND_KEYS:
                raise LabSchedulerError(f"rounds[{index}] possui envelope inválido.")
            cycle_id = item["cycle_id"]
            if not isinstance(cycle_id, str) or not cycle_id or cycle_id in seen:
                raise LabSchedulerError(f"rounds[{index}] possui cycle_id inválido ou duplicado.")
            seen.add(cycle_id)
            if not isinstance(item["state"], DigitalPhysiologyState):
                raise LabSchedulerError(f"rounds[{index}].state inválido.")
            if not isinstance(item["observation"], ResourceObservation):
                raise LabSchedulerError(f"rounds[{index}].observation inválida.")
            if not isinstance(item["base_budget"], InterestBudget):
                raise LabSchedulerError(f"rounds[{index}].base_budget inválido.")
            if not isinstance(item["backlog"], (list, tuple)):
                raise LabSchedulerError(f"rounds[{index}].backlog inválido.")
            for field in (
                "estimated_runtime_ms", "estimated_memory_mb",
                "estimated_test_evaluations",
            ):
                value = item[field]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise LabSchedulerError(f"rounds[{index}].{field} inválido.")
            normalized.append(item)
        return normalized

    def _observation_stop_reason(self, observation: ResourceObservation) -> str | None:
        checks = (
            ("cpu_load_limit", observation.cpu_load, self.policy.max_cpu_load),
            ("memory_pressure_limit", observation.memory_pressure, self.policy.max_memory_pressure),
            ("thermal_pressure_limit", observation.thermal_pressure, self.policy.max_thermal_pressure),
            ("energy_drain_limit", observation.energy_drain, self.policy.max_energy_drain),
        )
        for reason, observed, maximum in checks:
            if observed > maximum:
                return reason
        return None

    def run_batch(self, rounds: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """Run only bounded planning/admission cycles; no candidate code executes."""
        requests = self._validate_rounds(rounds)
        planned = []
        deferred = []
        total_runtime_ms = 0
        total_evaluations = 0
        peak_memory_mb = 0
        stop_reason = None

        for index, request in enumerate(requests):
            observation_reason = self._observation_stop_reason(request["observation"])
            if observation_reason:
                stop_reason = observation_reason
            elif total_runtime_ms + request["estimated_runtime_ms"] > self.policy.max_total_runtime_ms:
                stop_reason = "total_runtime_budget_exceeded"
            elif request["estimated_memory_mb"] > self.policy.max_peak_memory_mb:
                stop_reason = "peak_memory_budget_exceeded"
            elif total_evaluations + request["estimated_test_evaluations"] > self.policy.max_total_test_evaluations:
                stop_reason = "test_evaluation_budget_exceeded"

            if stop_reason:
                for remaining in requests[index:]:
                    deferred.append({
                        "cycle_id": remaining["cycle_id"],
                        "status": "deferred",
                        "reason": stop_reason,
                    })
                break

            result = self.persistent_cycle.run_cycle(
                cycle_id=request["cycle_id"],
                state=request["state"],
                observation=request["observation"],
                backlog=request["backlog"],
                base_budget=request["base_budget"],
            )
            total_runtime_ms += request["estimated_runtime_ms"]
            total_evaluations += request["estimated_test_evaluations"]
            peak_memory_mb = max(peak_memory_mb, request["estimated_memory_mb"])
            planned.append({
                "cycle_id": request["cycle_id"],
                "status": "planned",
                "declared_estimates": {
                    "runtime_ms": request["estimated_runtime_ms"],
                    "memory_mb": request["estimated_memory_mb"],
                    "test_evaluations": request["estimated_test_evaluations"],
                },
                "result": result,
            })

        return {
            "schema": "mahoraga.bounded_lab_schedule",
            "schema_version": 1,
            "scheduler_version": self.VERSION,
            "status": "completed" if not deferred else "partially_completed" if planned else "deferred",
            "planned_rounds": planned,
            "deferred_rounds": deferred,
            "stop_reason": stop_reason,
            "resource_accounting": {
                "basis": "caller_declared_estimates_and_observations",
                "estimated_total_runtime_ms": total_runtime_ms,
                "estimated_peak_memory_mb": peak_memory_mb,
                "estimated_total_test_evaluations": total_evaluations,
                "remaining_runtime_ms": self.policy.max_total_runtime_ms - total_runtime_ms,
                "remaining_test_evaluations": self.policy.max_total_test_evaluations - total_evaluations,
            },
            "candidate_code_executed": False,
            "tests_executed_by_scheduler": False,
            "background_service_started": False,
            "production_modified": False,
            "automatic_promotion": False,
        }
