"""Deterministic baseline/ablation benchmark for homeostasis-aware exploration.

All scenarios are synthetic. This benchmark compares advisory plans only; it
never discovers goals, persists memory, authorizes work, or executes actions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from experiments.cognitive_exploration_cycle import CognitiveExplorationCycle
from experiments.cognitive_interest_selector import CognitiveInterestSelector, InterestBudget
from experiments.digital_physiology import (
    DigitalHomeostasis,
    DigitalPhysiologyState,
    PhysiologyConfig,
    ResourceObservation,
)


VERSION = "0.1.0"
BASE_BUDGET = InterestBudget(max_runtime_ms=10_000, max_ram_mb=1024, max_selected=3)


def _candidates() -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": "high-value",
            "topic": "investigar hipótese relevante e controlável",
            "relevance": 0.90,
            "novelty": 0.80,
            "uncertainty": 0.90,
            "controllability": 0.90,
            "learning_progress": 0.90,
            "expected_transfer": 0.90,
            "noise_risk": 0.05,
            "estimated_runtime_ms": 1000,
            "estimated_ram_mb": 128,
            "dependencies": [],
            "evidence_refs": ["synthetic:high-value"],
        },
        {
            "candidate_id": "medium-value",
            "topic": "verificar relação secundária com transferência",
            "relevance": 0.75,
            "novelty": 0.60,
            "uncertainty": 0.50,
            "controllability": 0.80,
            "learning_progress": 0.70,
            "expected_transfer": 0.70,
            "noise_risk": 0.10,
            "estimated_runtime_ms": 1500,
            "estimated_ram_mb": 192,
            "dependencies": [],
            "evidence_refs": ["synthetic:medium-value"],
        },
        {
            "candidate_id": "noisy",
            "topic": "explorar sinal instável de baixa controlabilidade",
            "relevance": 0.80,
            "novelty": 0.90,
            "uncertainty": 0.90,
            "controllability": 0.20,
            "learning_progress": 0.40,
            "expected_transfer": 0.30,
            "noise_risk": 0.95,
            "estimated_runtime_ms": 500,
            "estimated_ram_mb": 64,
            "dependencies": [],
            "evidence_refs": ["synthetic:noisy"],
        },
    ]


def _summary(selection: dict[str, Any] | None) -> dict[str, Any]:
    if selection is None:
        return {
            "status": "deferred",
            "selected_ids": [],
            "selected_count": 0,
            "utility_score": 0.0,
            "aggregate_cost": {"runtime_ms": 0, "ram_mb": 0},
            "plan_sha256": None,
        }
    selected_ids = list(selection.get("selected_roots", []))
    scores = {
        item["candidate_id"]: item["score"]
        for item in selection.get("ranking", [])
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
    }
    aggregate = selection.get("aggregate_cost", {})
    return {
        "status": selection.get("status", "unknown"),
        "selected_ids": selected_ids,
        "selected_count": len(selected_ids),
        "utility_score": round(sum(scores.get(item, 0.0) for item in selected_ids), 8),
        "aggregate_cost": {
            "runtime_ms": aggregate.get("runtime_ms", 0),
            "ram_mb": aggregate.get("ram_mb", 0),
        },
        "plan_sha256": selection.get("plan_sha256"),
    }


def _run_case(
    scenario_id: str,
    state: DigitalPhysiologyState,
    observation: ResourceObservation,
    *,
    include_load_ablation: bool = False,
) -> dict[str, Any]:
    candidates = _candidates()
    selector = CognitiveInterestSelector()
    baseline = selector.select(candidates, BASE_BUDGET)
    adaptive_homeostasis = (
        DigitalHomeostasis(PhysiologyConfig(recovery_gain=0.0))
        if include_load_ablation else DigitalHomeostasis()
    )
    adaptive = CognitiveExplorationCycle(homeostasis=adaptive_homeostasis).plan(
        state=state,
        observation=observation,
        candidates=candidates,
        base_budget=BASE_BUDGET,
    )
    adaptive_selection = adaptive["selection"]
    report = {
        "scenario_id": scenario_id,
        "synthetic_only": True,
        "baseline_without_homeostasis": _summary(baseline),
        "homeostasis_adaptive": _summary(adaptive_selection),
        "control_state": adaptive["physiology"]["state"]["control_state"],
        "effective_exploration_factor": adaptive["effective_exploration_factor"],
        "adaptive_status": adaptive["status"],
        "execution_performed": adaptive["work_executed"],
        "authorization_granted": adaptive["authorization_granted"],
    }
    if include_load_ablation:
        # Hold all non-load inputs constant and disable recovery coupling so
        # the ablation isolates the cognitive-load state/observation channel.
        no_load_state = DigitalPhysiologyState(
            cycle=state.cycle,
            energy_reserve=state.energy_reserve,
            thermal_load=state.thermal_load,
            memory_pressure=state.memory_pressure,
            cognitive_load=0.02,
            recovery_reserve=state.recovery_reserve,
            control_state=state.control_state,
        )
        no_load_observation = ResourceObservation(
            cpu_load=observation.cpu_load,
            memory_pressure=observation.memory_pressure,
            thermal_pressure=observation.thermal_pressure,
            energy_drain=observation.energy_drain,
            cooling=observation.cooling,
            recharge=observation.recharge,
            task_load=0.02,
            unresolved_uncertainty=observation.unresolved_uncertainty,
            expected_learning_progress=observation.expected_learning_progress,
            noise_risk=observation.noise_risk,
            source="simulated",
        )
        no_load_cycle = CognitiveExplorationCycle(
            homeostasis=DigitalHomeostasis(PhysiologyConfig(recovery_gain=0.0))
        )
        # Match the full-load branch's recovery coupling for a clean ablation.
        full_load_state = DigitalPhysiologyState(
            cycle=state.cycle,
            energy_reserve=state.energy_reserve,
            thermal_load=state.thermal_load,
            memory_pressure=state.memory_pressure,
            cognitive_load=state.cognitive_load,
            recovery_reserve=state.recovery_reserve,
            control_state=state.control_state,
        )
        full_load_cycle = CognitiveExplorationCycle(
            homeostasis=DigitalHomeostasis(PhysiologyConfig(recovery_gain=0.0))
        )
        full_load = full_load_cycle.plan(
            state=full_load_state,
            observation=ResourceObservation(
                cpu_load=observation.cpu_load,
                memory_pressure=observation.memory_pressure,
                thermal_pressure=observation.thermal_pressure,
                energy_drain=observation.energy_drain,
                cooling=observation.cooling,
                recharge=observation.recharge,
                task_load=observation.task_load,
                unresolved_uncertainty=observation.unresolved_uncertainty,
                expected_learning_progress=observation.expected_learning_progress,
                noise_risk=observation.noise_risk,
                source="simulated",
            ),
            candidates=candidates,
            base_budget=BASE_BUDGET,
        )
        no_load = no_load_cycle.plan(
            state=no_load_state,
            observation=no_load_observation,
            candidates=candidates,
            base_budget=BASE_BUDGET,
        )
        report["load_ablation"] = {
            "full_load_factor": full_load["effective_exploration_factor"],
            "no_load_factor": no_load["effective_exploration_factor"],
            "full_load": _summary(full_load["selection"]),
            "no_load": _summary(no_load["selection"]),
        }
        # A 2x2 factorial ablation separates persistent cognitive-load state
        # from the caller-supplied current task-load observation. All other
        # inputs and the recovery coupling are held constant.
        factorial = {}
        for state_label, state_load in (("low", 0.02), ("high", 0.90)):
            for task_label, task_load in (("low", 0.02), ("high", 0.90)):
                variant_state = DigitalPhysiologyState(
                    cycle=state.cycle,
                    energy_reserve=state.energy_reserve,
                    thermal_load=state.thermal_load,
                    memory_pressure=state.memory_pressure,
                    cognitive_load=state_load,
                    recovery_reserve=state.recovery_reserve,
                    control_state=state.control_state,
                )
                variant_observation = ResourceObservation(
                    cpu_load=observation.cpu_load,
                    memory_pressure=observation.memory_pressure,
                    thermal_pressure=observation.thermal_pressure,
                    energy_drain=observation.energy_drain,
                    cooling=observation.cooling,
                    recharge=observation.recharge,
                    task_load=task_load,
                    unresolved_uncertainty=observation.unresolved_uncertainty,
                    expected_learning_progress=observation.expected_learning_progress,
                    noise_risk=observation.noise_risk,
                    source="simulated",
                )
                variant = CognitiveExplorationCycle(
                    homeostasis=DigitalHomeostasis(PhysiologyConfig(recovery_gain=0.0))
                ).plan(
                    state=variant_state,
                    observation=variant_observation,
                    candidates=candidates,
                    base_budget=BASE_BUDGET,
                )
                factorial[f"state_{state_label}__task_{task_label}"] = {
                    "state_cognitive_load": state_load,
                    "observed_task_load": task_load,
                    "control_state": variant["physiology"]["state"]["control_state"],
                    "effective_exploration_factor": variant["effective_exploration_factor"],
                    "status": variant["status"],
                    "selection": _summary(variant["selection"]),
                    "work_executed": variant["work_executed"],
                    "authorization_granted": variant["authorization_granted"],
                }
        report["load_factorial_ablation"] = factorial
    return report


def run_cognitive_exploration_benchmark() -> dict[str, Any]:
    """Compare fixed-budget selection with homeostasis and a load ablation."""
    healthy_state = DigitalPhysiologyState(
        energy_reserve=0.98,
        thermal_load=0.02,
        memory_pressure=0.02,
        cognitive_load=0.02,
        recovery_reserve=0.90,
    )
    healthy_observation = ResourceObservation(
        cpu_load=0.02,
        memory_pressure=0.02,
        thermal_pressure=0.02,
        energy_drain=0.01,
        cooling=0.90,
        recharge=0.05,
        task_load=0.02,
        unresolved_uncertainty=0.90,
        expected_learning_progress=0.95,
        noise_risk=0.01,
    )
    load_state = DigitalPhysiologyState(
        energy_reserve=0.98,
        thermal_load=0.02,
        memory_pressure=0.02,
        cognitive_load=0.90,
        recovery_reserve=0.90,
    )
    load_observation = ResourceObservation(
        cpu_load=0.02,
        memory_pressure=0.02,
        thermal_pressure=0.02,
        energy_drain=0.01,
        cooling=0.90,
        recharge=0.05,
        task_load=0.90,
        unresolved_uncertainty=0.90,
        expected_learning_progress=0.95,
        noise_risk=0.01,
    )
    critical_state = DigitalPhysiologyState(
        energy_reserve=0.98,
        thermal_load=0.98,
        memory_pressure=0.02,
        cognitive_load=0.02,
        recovery_reserve=0.90,
    )
    critical_observation = ResourceObservation(
        cpu_load=0.80,
        memory_pressure=0.02,
        thermal_pressure=0.90,
        energy_drain=0.10,
        cooling=0.0,
        recharge=0.0,
        task_load=0.02,
        unresolved_uncertainty=0.90,
        expected_learning_progress=0.95,
        noise_risk=0.01,
    )
    payload = {
        "schema": "mahoraga.cognitive_exploration_benchmark",
        "schema_version": 1,
        "benchmark_version": VERSION,
        "scenarios": [
            _run_case("healthy", healthy_state, healthy_observation),
            _run_case(
                "high_cognitive_load",
                load_state,
                load_observation,
                include_load_ablation=True,
            ),
            _run_case("critical_pressure", critical_state, critical_observation),
        ],
        "synthetic_only": True,
        "hardware_telemetry_used": False,
        "memory_persisted": False,
        "goal_created": False,
        "work_executed": False,
        "authorization_granted": False,
        "limitations": [
            "Candidate values and resource estimates are synthetic and caller-declared.",
            "The benchmark compares advisory plans, not actual learning outcomes.",
            "The baseline intentionally ignores homeostatic state.",
            "The load ablation isolates only the modeled cognitive-load channel.",
            "No Android telemetry, scheduler, tool adapter or runtime capability is used.",
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    payload["benchmark_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload
