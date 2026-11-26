"""Bounded digital physiology and homeostatic regulation research model.

The state variables are computational control signals, not emotions,
sensations, consciousness indicators, or measurements of biological life.
This model consumes supplied observations only; it never reads hardware,
persists state, schedules work, or authorizes actions.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any


class DigitalPhysiologyError(ValueError):
    """Invalid digital-physiology state, observation, or control parameter."""


def _unit(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DigitalPhysiologyError(f"{field} deve ser número entre 0 e 1.")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DigitalPhysiologyError(
            f"{field} deve ser finito e estar entre 0 e 1."
        ) from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise DigitalPhysiologyError(f"{field} deve ser finito e estar entre 0 e 1.")
    return number


@dataclass(frozen=True)
class ResourceObservation:
    """One bounded input sample supplied by a caller or a simulator.

    All measurements are normalized to [0, 1]. They are caller-declared;
    the model does not authenticate device sensors or inspect hardware.
    """

    cpu_load: float
    memory_pressure: float
    thermal_pressure: float
    energy_drain: float
    cooling: float
    recharge: float
    task_load: float
    unresolved_uncertainty: float
    expected_learning_progress: float
    noise_risk: float
    source: str = "simulated"

    def __post_init__(self) -> None:
        for name in (
            "cpu_load", "memory_pressure", "thermal_pressure", "energy_drain",
            "cooling", "recharge", "task_load", "unresolved_uncertainty",
            "expected_learning_progress", "noise_risk",
        ):
            object.__setattr__(self, name, _unit(getattr(self, name), name))
        if not isinstance(self.source, str) or self.source not in {"simulated", "caller_observed"}:
            raise DigitalPhysiologyError("source precisa ser simulated ou caller_observed.")


@dataclass(frozen=True)
class PhysiologyConfig:
    """Stable set points and bounded response coefficients."""

    energy_drain_gain: float = 0.16
    recharge_gain: float = 0.12
    thermal_gain: float = 0.22
    cooling_gain: float = 0.18
    memory_smoothing: float = 0.40
    load_smoothing: float = 0.40
    thermal_smoothing: float = 0.35
    recovery_gain: float = 0.10
    low_energy_threshold: float = 0.25
    resume_energy_threshold: float = 0.45
    high_thermal_threshold: float = 0.78
    resume_thermal_threshold: float = 0.58
    high_memory_threshold: float = 0.88
    resume_memory_threshold: float = 0.68
    high_load_threshold: float = 0.82
    resume_load_threshold: float = 0.62
    critical_pressure_threshold: float = 0.94

    def __post_init__(self) -> None:
        for name in (
            "energy_drain_gain", "recharge_gain", "thermal_gain",
            "cooling_gain", "memory_smoothing", "load_smoothing",
            "thermal_smoothing", "recovery_gain", "low_energy_threshold",
            "resume_energy_threshold", "high_thermal_threshold",
            "resume_thermal_threshold", "high_memory_threshold",
            "resume_memory_threshold", "high_load_threshold", "resume_load_threshold",
            "critical_pressure_threshold",
        ):
            object.__setattr__(self, name, _unit(getattr(self, name), name))
        if self.resume_energy_threshold <= self.low_energy_threshold:
            raise DigitalPhysiologyError("O limiar de retomada de energia deve ser maior que o limiar baixo.")
        if self.resume_thermal_threshold >= self.high_thermal_threshold:
            raise DigitalPhysiologyError("O limiar térmico de retomada deve ser menor que o limiar alto.")
        if self.resume_memory_threshold >= self.high_memory_threshold:
            raise DigitalPhysiologyError("O limiar de memória de retomada deve ser menor que o limiar alto.")
        if self.resume_load_threshold >= self.high_load_threshold:
            raise DigitalPhysiologyError("O limiar de retomada de carga deve ser menor que o limiar alto.")
        if self.critical_pressure_threshold <= max(
            self.high_thermal_threshold, self.high_memory_threshold, self.high_load_threshold
        ):
            raise DigitalPhysiologyError("O limiar crítico deve superar os limiares altos.")


@dataclass(frozen=True)
class DigitalPhysiologyState:
    cycle: int = 0
    energy_reserve: float = 0.85
    thermal_load: float = 0.10
    memory_pressure: float = 0.10
    cognitive_load: float = 0.10
    recovery_reserve: float = 0.50
    control_state: str = "normal"

    def __post_init__(self) -> None:
        if isinstance(self.cycle, bool) or not isinstance(self.cycle, int) or self.cycle < 0:
            raise DigitalPhysiologyError("cycle deve ser inteiro não negativo.")
        for name in (
            "energy_reserve", "thermal_load", "memory_pressure",
            "cognitive_load", "recovery_reserve",
        ):
            object.__setattr__(self, name, _unit(getattr(self, name), name))
        if not isinstance(self.control_state, str) or self.control_state not in {
            "normal", "reduce_work", "pause", "recovering"
        }:
            raise DigitalPhysiologyError("control_state inválido.")


class DigitalHomeostasis:
    """Pure state-transition function for a simulated digital organism.

    It estimates resource strain and recommends a bounded admission factor.
    The recommendation is advisory only: the autonomy governor remains the
    runtime authority and is not called by this experiment.
    """

    VERSION = "0.2.0"
    CONTROL_FACTORS = MappingProxyType({
        "normal": 1.0,
        "reduce_work": 0.5,
        "pause": 0.0,
        "recovering": 0.25,
    })

    def __init__(self, config: PhysiologyConfig | None = None):
        if config is not None and not isinstance(config, PhysiologyConfig):
            raise DigitalPhysiologyError("config precisa ser PhysiologyConfig.")
        self.config = config or PhysiologyConfig()

    @staticmethod
    def _clamp(value: float) -> float:
        if not math.isfinite(value):
            raise DigitalPhysiologyError("Transição produziu valor não finito.")
        return min(1.0, max(0.0, value))

    def update(
        self,
        state: DigitalPhysiologyState,
        observation: ResourceObservation,
    ) -> dict[str, Any]:
        if not isinstance(state, DigitalPhysiologyState):
            raise DigitalPhysiologyError("state precisa ser DigitalPhysiologyState.")
        if not isinstance(observation, ResourceObservation):
            raise DigitalPhysiologyError("observation precisa ser ResourceObservation.")

        cfg = self.config
        energy = self._clamp(
            state.energy_reserve
            - observation.energy_drain * cfg.energy_drain_gain
            + observation.recharge * cfg.recharge_gain
        )
        thermal = self._clamp(
            state.thermal_load * (1.0 - cfg.thermal_smoothing)
            + observation.thermal_pressure * cfg.thermal_smoothing
            + observation.cpu_load * cfg.thermal_gain
            - observation.cooling * cfg.cooling_gain
        )
        memory = self._clamp(
            state.memory_pressure * (1.0 - cfg.memory_smoothing)
            + observation.memory_pressure * cfg.memory_smoothing
        )
        load = self._clamp(
            state.cognitive_load * (1.0 - cfg.load_smoothing)
            + observation.task_load * cfg.load_smoothing
        )
        recovery = self._clamp(
            state.recovery_reserve
            + cfg.recovery_gain * (
                (1.0 - observation.cpu_load)
                * (1.0 - observation.task_load)
                * observation.cooling
                + observation.recharge
                - observation.energy_drain
            )
        )

        critical = (
            energy <= cfg.low_energy_threshold * 0.50
            or thermal >= cfg.critical_pressure_threshold
            or memory >= cfg.critical_pressure_threshold
            or load >= cfg.critical_pressure_threshold
        )
        strained = (
            energy < cfg.low_energy_threshold
            or thermal >= cfg.high_thermal_threshold
            or memory >= cfg.high_memory_threshold
            or load >= cfg.high_load_threshold
        )
        recovered = (
            energy >= cfg.resume_energy_threshold
            and thermal <= cfg.resume_thermal_threshold
            and memory <= cfg.resume_memory_threshold
            and load <= cfg.resume_load_threshold
        )

        if critical:
            control_state = "pause"
        elif state.control_state == "pause":
            control_state = "recovering" if recovered else "pause"
        elif state.control_state == "recovering":
            control_state = "normal" if recovered else "recovering"
            if strained:
                control_state = "reduce_work"
        elif strained:
            control_state = "reduce_work"
        else:
            control_state = "normal"

        # Attention and exploration are bounded computational allocations.
        # They are not claims about felt attention, curiosity, or emotion.
        physiological_capacity = (
            energy * (1.0 - thermal) * (1.0 - memory) * (1.0 - load)
        )
        admission = self._clamp(
            self.CONTROL_FACTORS[control_state]
            * (0.50 + 0.50 * recovery)
        )
        attention_budget = self._clamp(physiological_capacity * admission)
        exploration_budget = self._clamp(
            attention_budget
            * observation.unresolved_uncertainty
            * observation.expected_learning_progress
            * (1.0 - observation.noise_risk)
        )
        homeostatic_error = self._clamp(
            max(
                0.0,
                cfg.low_energy_threshold - energy,
                thermal - cfg.resume_thermal_threshold,
                memory - cfg.resume_memory_threshold,
                load - cfg.resume_load_threshold,
            )
        )

        next_state = DigitalPhysiologyState(
            cycle=state.cycle + 1,
            energy_reserve=energy,
            thermal_load=thermal,
            memory_pressure=memory,
            cognitive_load=load,
            recovery_reserve=recovery,
            control_state=control_state,
        )
        return {
            "schema": "mahoraga.digital_physiology_state",
            "schema_version": 1,
            "engine_version": self.VERSION,
            "state": {
                "cycle": next_state.cycle,
                "energy_reserve": next_state.energy_reserve,
                "thermal_load": next_state.thermal_load,
                "memory_pressure": next_state.memory_pressure,
                "cognitive_load": next_state.cognitive_load,
                "recovery_reserve": next_state.recovery_reserve,
                "control_state": next_state.control_state,
            },
            "regulation": {
                "homeostatic_error": homeostatic_error,
                "recommended_admission_factor": admission,
                "attention_budget": attention_budget,
                "exploration_budget": exploration_budget,
                "recommended_action": control_state,
                "advisory_only": True,
                "authorization_granted": False,
            },
            "observation": {
                "source": observation.source,
                "authenticated": False,
            },
            "side_effects": {
                "hardware_read": False,
                "memory_persisted": False,
                "work_dispatched": False,
                "autonomy_governor_called": False,
            },
            "interpretation_limits": [
                "State variables are computational resource-control signals, not emotions or subjective states.",
                "Observations are caller-supplied and unauthenticated.",
                "The model does not read hardware, persist state, schedule work, or authorize execution.",
                "The admission factor is a recommendation; production governance remains external.",
            ],
        }
