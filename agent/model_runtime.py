"""Governed local language-model runtime for Mahoraga."""
from __future__ import annotations
import base64
import hashlib
import json
import re
import subprocess
import threading
import time
import uuid
import math
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

class ModelRuntimeError(RuntimeError):
    """Base error for local model lifecycle and inference failures."""

class ModelUnavailableError(ModelRuntimeError):
    """Selected local inference backend is unavailable."""

class ModelAdmissionError(ModelRuntimeError):
    """Current device resources do not admit model execution."""

class ModelDeadlineExceeded(ModelRuntimeError):
    """A cooperative inference deadline was exceeded."""

class ModelInferenceCancelled(ModelRuntimeError):
    """An inference request reached a confirmed cancelled terminal state."""


_DEFAULT_TASK_DURATION_SECONDS = {
    "interactive": 30.0,
    "reasoning": 120.0,
    "maintenance": 180.0,
    "background": 300.0,
}
_MAX_TASK_DURATION_MULTIPLIER = 2.0


def _max_task_duration_seconds(task_class: str) -> float:
    """Return the same hard per-class ceiling enforced by the Android owner."""
    return _DEFAULT_TASK_DURATION_SECONDS[task_class] * _MAX_TASK_DURATION_MULTIPLIER


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model_path: Path
    format: str = "litertlm"
    backend_name: str = "cpu"
    expected_sha256: str | None = None
    max_prompt_chars: int = 6_000
    context_window_tokens: int = 4_096
    max_output_chars: int = 16_000
    cache_dir: Path | None = None
    estimated_peak_ram_mb: int | None = None
    runtime_overhead_mb: int = 768
    system_memory_reserve_mb: int = 512
    minimum_free_storage_mb: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id precisa ser texto não vazio.")
        if self.format != "litertlm":
            raise ValueError("Formato ainda não suportado; esperado litertlm.")
        if not isinstance(self.backend_name, str) or self.backend_name not in {"cpu", "gpu"}:
            raise ValueError("backend_name precisa ser cpu ou gpu.")
        for name in ("max_prompt_chars", "max_output_chars", "context_window_tokens",
                     "runtime_overhead_mb", "system_memory_reserve_mb"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} precisa ser inteiro.")
        if self.max_prompt_chars < 1 or self.max_output_chars < 1:
            raise ValueError("Limites de texto precisam ser positivos.")
        if self.context_window_tokens < 512:
            raise ValueError("context_window_tokens precisa ser pelo menos 512.")
        for name in ("estimated_peak_ram_mb", "minimum_free_storage_mb"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} precisa ser inteiro positivo quando informado.")
        if self.runtime_overhead_mb < 0 or self.system_memory_reserve_mb < 0:
            raise ValueError("Reservas de memória não podem ser negativas.")
        if self.expected_sha256 is not None:
            if not isinstance(self.expected_sha256, str):
                raise ValueError("expected_sha256 precisa ser texto hexadecimal.")
            digest = self.expected_sha256.strip().lower()
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("expected_sha256 precisa conter 64 caracteres hexadecimais.")
            object.__setattr__(self, "expected_sha256", digest)
        if self.model_path is None:
            raise ValueError("model_path é obrigatório.")
        try:
            object.__setattr__(self, "model_path", Path(self.model_path).expanduser())
        except (TypeError, ValueError) as exc:
            raise ValueError("model_path inválido.") from exc
        cache_dir = self.cache_dir
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "mahoraga" / "litert"
        try:
            object.__setattr__(self, "cache_dir", Path(cache_dir).expanduser())
        except (TypeError, ValueError) as exc:
            raise ValueError("cache_dir inválido.") from exc

@dataclass(frozen=True)
class ResourceRequest:
    """Per-task resource budget selected by Mahoraga."""
    task_class: str = "interactive"
    priority: int = 50
    estimated_peak_ram_mb: int | None = None
    estimated_additional_ram_mb: int | None = None
    thinking_token_budget: int | None = None
    max_output_tokens: int | None = None
    # Qwen3 thinking-mode recommendations: temperature=0.6, top_p=0.95, top_k=20.
    top_k: int | None = 20
    top_p: float | None = 0.95
    temperature: float | None = 0.6
    minimum_available_ram_mb: int | None = None
    minimum_free_storage_mb: int | None = None
    max_duration_seconds: float | None = None
    duration_policy_applied: bool = True
    allow_background: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.task_class, str) or self.task_class not in {
            "interactive", "reasoning", "maintenance", "background"
        }:
            raise ValueError("task_class não reconhecida.")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int) or not 0 <= self.priority <= 100:
            raise ValueError("priority precisa ser inteiro entre 0 e 100.")
        for name in ("estimated_peak_ram_mb", "estimated_additional_ram_mb",
                     "thinking_token_budget", "max_output_tokens",
                     "minimum_available_ram_mb", "minimum_free_storage_mb"):
            value = getattr(self, name)
            minimum = 0 if name == "thinking_token_budget" else 1
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < minimum
            ):
                raise ValueError(f"{name} precisa ser inteiro válido quando informado.")
        if self.thinking_token_budget is not None and self.thinking_token_budget > 2048:
            raise ValueError("thinking_token_budget não pode exceder 2048.")
        if self.max_output_tokens is not None and self.max_output_tokens > 2048:
            raise ValueError("max_output_tokens não pode exceder 2048.")
        if not isinstance(self.duration_policy_applied, bool):
            raise ValueError("duration_policy_applied precisa ser booleano.")
        if not isinstance(self.allow_background, bool):
            raise ValueError("allow_background precisa ser booleano.")
        if self.task_class == "background" and self.allow_background is not True:
            raise ValueError("classe background exige allow_background=True.")
        if self.allow_background is True and self.task_class != "background":
            raise ValueError("allow_background=True exige classe background.")
        if self.top_k is not None and (
            isinstance(self.top_k, bool) or not isinstance(self.top_k, int)
            or not 1 <= self.top_k <= 256
        ):
            raise ValueError("top_k precisa ser um inteiro entre 1 e 256.")
        if self.top_p is not None and (
            isinstance(self.top_p, bool) or not isinstance(self.top_p, (int, float))
            or not math.isfinite(self.top_p) or not 0 <= self.top_p <= 1
        ):
            raise ValueError("top_p precisa ser finito e estar entre 0 e 1.")
        if self.temperature is not None and (
            isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2
        ):
            raise ValueError("temperature precisa ser finita e estar entre 0 e 2.")
        if self.max_duration_seconds is not None and (
            isinstance(self.max_duration_seconds, bool)
            or not isinstance(self.max_duration_seconds, (int, float))
            or not math.isfinite(self.max_duration_seconds)
            or self.max_duration_seconds <= 0
        ):
            raise ValueError("max_duration_seconds precisa ser finito e positivo.")
        # The Python LiteRT backend is normally the first backend selected. Enforce
        # the native Android owner's ceiling here as well, so an explicit caller
        # request cannot create an effectively unbounded local watchdog.
        if self.max_duration_seconds is not None:
            ceiling = _max_task_duration_seconds(self.task_class)
            if self.max_duration_seconds > ceiling:
                object.__setattr__(self, "max_duration_seconds", ceiling)


class AdaptiveBudgetPlanner:
    """Build task-specific budgets from model size and current device conditions."""
    DEFAULT_DURATION_SECONDS = dict(_DEFAULT_TASK_DURATION_SECONDS)
    MAX_DURATION_MULTIPLIER = _MAX_TASK_DURATION_MULTIPLIER

    def __init__(self, hardware: Any, runtime_context_reader=None,
                 duration_profiles: dict | None = None) -> None:
        if hardware is None:
            raise ValueError("hardware é obrigatório para planejar recursos.")
        self.hardware = hardware
        self.runtime_context_reader = runtime_context_reader
        self.duration_profiles = dict(self.DEFAULT_DURATION_SECONDS)
        if duration_profiles:
            for task, seconds in duration_profiles.items():
                if (task not in self.duration_profiles
                        or isinstance(seconds, bool)
                        or not math.isfinite(float(seconds))
                        or float(seconds) <= 0):
                    raise ValueError("Perfil de duração inválido.")
                self.duration_profiles[task] = float(seconds)

    def for_task(self, spec: ModelSpec, task_class: str = "interactive", *,
                 priority: int = 50, requested_duration_seconds: float | None = None,
                 allow_background: bool = False) -> ResourceRequest:
        if task_class not in self.duration_profiles:
            raise ValueError("task_class não reconhecida.")
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100:
            raise ValueError("priority precisa estar entre 0 e 100.")
        try:
            model_size_mb = spec.model_path.stat().st_size / (1024 * 1024)
        except OSError as exc:
            raise ModelRuntimeError("Não foi possível estimar o tamanho do modelo.") from exc

        task_memory_factor = 1.25 if task_class == "reasoning" else 1.0
        if spec.backend_name == "gpu":
            base_peak = max(1024, model_size_mb * 0.75 + 512)
        else:
            base_peak = model_size_mb * 1.5 + spec.runtime_overhead_mb
        estimated_peak = math.ceil(base_peak * task_memory_factor)

        if requested_duration_seconds is not None and (
            isinstance(requested_duration_seconds, bool)
            or not isinstance(requested_duration_seconds, (int, float))
            or not math.isfinite(requested_duration_seconds)
            or requested_duration_seconds <= 0
        ):
            raise ValueError("requested_duration_seconds precisa ser finito e positivo.")
        duration_cap = _max_task_duration_seconds(task_class)
        duration = min(
            float(requested_duration_seconds)
            if requested_duration_seconds is not None
            else self.duration_profiles[task_class],
            duration_cap,
        )
        # Priority 50 is neutral; lower priority receives less time, higher priority more.
        # Priority may raise the selected budget but never above the task-class ceiling.
        duration = min(duration * (0.75 + (priority / 200.0)), duration_cap)
        context = {}
        if callable(self.runtime_context_reader):
            try:
                context = self.runtime_context_reader() or {}
            except Exception:
                context = {}
        thermal = context.get("thermal_status", "unknown") if isinstance(context, dict) else "unknown"
        thermal = thermal.casefold() if isinstance(thermal, str) else "unknown"
        if thermal in {"moderate", "light-moderate"}:
            duration *= 0.75
        elif thermal in {"unknown", ""}:
            duration *= 0.85

        try:
            snapshot = self.hardware.resource_snapshot()
        except Exception:
            snapshot = {}
        battery = snapshot.get("battery", {}) if isinstance(snapshot, dict) else {}
        api_data = battery.get("termux_api", {}).get("data", {}) if isinstance(battery, dict) else {}
        percentage = api_data.get("percentage") if isinstance(api_data, dict) else None
        status = api_data.get("status") if isinstance(api_data, dict) else None
        if not isinstance(percentage, (int, float)) or isinstance(percentage, bool):
            sysfs = battery.get("sysfs_read_only", {}) if isinstance(battery, dict) else {}
            raw_capacity = sysfs.get("capacity") if isinstance(sysfs, dict) else None
            try:
                percentage = float(raw_capacity)
            except (TypeError, ValueError):
                percentage = None
            if status is None and isinstance(sysfs, dict):
                status = sysfs.get("status")
        if (isinstance(percentage, (int, float)) and not isinstance(percentage, bool)
                and percentage < 15 and str(status).casefold() not in {"charging", "full"}):
            duration *= 0.6

        additional_memory = {
            "interactive": 512,
            "reasoning": 1024,
            "maintenance": 384,
            "background": 256,
        }[task_class]
        thinking_budget = {
            "interactive": 256,
            "reasoning": 1024,
            "maintenance": 512,
            "background": 256,
        }[task_class]
        output_budget = {
            "interactive": 512,
            "reasoning": 1024,
            "maintenance": 768,
            "background": 512,
        }[task_class]
        return ResourceRequest(
            task_class=task_class,
            priority=priority,
            estimated_peak_ram_mb=estimated_peak,
            estimated_additional_ram_mb=additional_memory,
            thinking_token_budget=thinking_budget,
            max_output_tokens=output_budget,
            max_duration_seconds=max(1.0, round(duration, 2)),
            duration_policy_applied=True,
            allow_background=allow_background,
        )

    def __call__(self, spec: ModelSpec) -> ResourceRequest:
        return self.for_task(spec, "interactive")


class ModelBackend(Protocol):
    """Minimal backend contract; Mahoraga modules do not depend on LiteRT directly."""
    def load(self, model_path: Path) -> None: ...
    def generate(self, prompt: str, *, request: ResourceRequest) -> str: ...
    def close(self) -> None: ...

class ModelResourcePolicy:
    """Fail-closed admission using the existing read-only hardware collector."""
    BLOCKING_THERMAL_STATES = {"severe", "critical", "emergency", "shutdown"}

    def __init__(self, hardware: Any, runtime_context_reader=None) -> None:
        if hardware is None:
            raise ValueError("hardware é obrigatório para admissão do modelo.")
        self.hardware = hardware
        self.runtime_context_reader = runtime_context_reader

    @staticmethod
    def _available_ram_mb(snapshot: dict) -> float | None:
        memory = snapshot.get("memory")
        values = memory.get("values") if isinstance(memory, dict) else None
        available = values.get("MemAvailable") if isinstance(values, dict) else None
        value = available.get("mb") if isinstance(available, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _total_ram_mb(snapshot: dict) -> float | None:
        memory = snapshot.get("memory")
        values = memory.get("values") if isinstance(memory, dict) else None
        total = values.get("MemTotal") if isinstance(values, dict) else None
        value = total.get("mb") if isinstance(total, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _free_storage_mb(snapshot: dict, cache_path: Path) -> float | None:
        storage = snapshot.get("storage")
        if not isinstance(storage, dict):
            return None
        try:
            target = cache_path.expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        matches = []
        for item in storage.values():
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            value = item.get("free_bytes")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                continue
            try:
                mount = Path(item["path"]).expanduser().resolve()
                if target.is_relative_to(mount):
                    matches.append((len(str(mount)), float(value) / (1024 * 1024)))
            except (OSError, RuntimeError):
                continue
        return max(matches, key=lambda item: item[0])[1] if matches else None

    def evaluate(self, spec: ModelSpec, *, phase: str = "load",
                 request: ResourceRequest | None = None) -> dict:
        if phase not in {"load", "inference"}:
            return {"allowed": False, "reason": "unknown_admission_phase"}
        request = request or ResourceRequest()
        reader = getattr(self.hardware, "resource_snapshot", None)
        if not callable(reader):
            return {"allowed": False, "reason": "resource_snapshot_unavailable"}
        try:
            snapshot = reader()
        except Exception as exc:
            return {"allowed": False, "reason": "resource_snapshot_failed",
                    "error": type(exc).__name__}
        if not isinstance(snapshot, dict):
            return {"allowed": False, "reason": "resource_snapshot_invalid"}

        ram_mb = self._available_ram_mb(snapshot)
        total_ram_mb = self._total_ram_mb(snapshot)
        # LiteRT-LM writes compiled/runtime artifacts to cache_dir. The model
        # file may live on a different mount, so checking its mount can admit a
        # load even when the actual runtime cache volume is full.
        storage_mb = (
            self._free_storage_mb(snapshot, spec.cache_dir)
            if phase == "load" else None
        )
        if ram_mb is None:
            return {"allowed": False, "reason": "available_ram_unknown"}
        if phase == "load" and storage_mb is None:
            return {"allowed": False, "reason": "free_storage_unknown"}
        try:
            model_size_mb = spec.model_path.stat().st_size / (1024 * 1024)
        except OSError:
            return {"allowed": False, "reason": "model_size_unavailable"}

        if spec.estimated_peak_ram_mb is not None:
            calculated_peak = spec.estimated_peak_ram_mb
        elif spec.backend_name == "gpu":
            calculated_peak = math.ceil(max(1024, model_size_mb * 0.75 + 512))
        else:
            calculated_peak = math.ceil(model_size_mb * 1.5 + spec.runtime_overhead_mb)
        baseline_peak = calculated_peak
        estimated_peak = max(baseline_peak, request.estimated_peak_ram_mb or 0)
        load_reserve_mb = max(
            spec.system_memory_reserve_mb,
            math.ceil(total_ram_mb * 0.08) if total_ram_mb is not None else 0,
        )
        inference_reserve_mb = max(
            384,
            spec.system_memory_reserve_mb // 2,
            math.ceil(total_ram_mb * 0.04) if total_ram_mb is not None else 0,
        )
        if phase == "load":
            required_ram_mb = estimated_peak + load_reserve_mb
        else:
            baseline_additional = {
                "interactive": 512,
                "reasoning": 1024,
                "maintenance": 384,
                "background": 256,
            }[request.task_class]
            additional_ram = max(
                baseline_additional, request.estimated_additional_ram_mb or 0
            )
            required_ram_mb = additional_ram + inference_reserve_mb
        if request.minimum_available_ram_mb is not None:
            required_ram_mb = max(required_ram_mb, request.minimum_available_ram_mb)
        if ram_mb < required_ram_mb:
            return {"allowed": False, "reason": "insufficient_available_ram",
                    "available_ram_mb": ram_mb, "required_ram_mb": required_ram_mb,
                    "estimated_peak_ram_mb": estimated_peak,
                    "phase": phase, "task_class": request.task_class}

        required_storage_mb = request.minimum_free_storage_mb
        if required_storage_mb is None:
            required_storage_mb = spec.minimum_free_storage_mb
        if required_storage_mb is None:
            required_storage_mb = max(256, math.ceil(model_size_mb * 0.10))
        if phase == "inference":
            required_storage_mb = 0
        if phase == "load" and storage_mb < required_storage_mb:
            return {"allowed": False, "reason": "insufficient_free_storage",
                    "free_storage_mb": storage_mb,
                    "required_storage_mb": required_storage_mb}

        context = {}
        if callable(self.runtime_context_reader):
            try:
                context = self.runtime_context_reader()
            except Exception as exc:
                return {"allowed": False, "reason": "runtime_context_failed",
                        "error": type(exc).__name__}
        if context is None:
            context = {}
        if not isinstance(context, dict):
            return {"allowed": False, "reason": "runtime_context_invalid"}
        if request.allow_background is not True:
            if context.get("app_foreground") is not True:
                return {"allowed": False, "reason": "foreground_state_not_confirmed"}
            if context.get("screen_interactive") is not True:
                return {"allowed": False, "reason": "interactive_screen_state_not_confirmed"}
        elif context.get("app_foreground") is not True and request.task_class != "background":
            return {"allowed": False, "reason": "background_task_class_not_authorized"}

        thermal = context.get("thermal_status")
        if isinstance(thermal, str) and thermal.strip().casefold() in self.BLOCKING_THERMAL_STATES:
            return {"allowed": False, "reason": "thermal_state_blocks_model_load",
                    "thermal_status": thermal.strip().casefold()}
        return {
            "allowed": True,
            "reason": "foreground_model_resources_admitted",
            "phase": phase,
            "task_class": request.task_class,
            "available_ram_mb": round(ram_mb, 2),
            "estimated_peak_ram_mb": estimated_peak,
            "estimated_additional_ram_mb": (
                additional_ram if phase == "inference" else None
            ),
            "load_reserve_mb": load_reserve_mb,
            "inference_reserve_mb": inference_reserve_mb,
            "total_ram_mb": total_ram_mb,
            "required_ram_mb": required_ram_mb,
            "free_storage_mb": round(storage_mb, 2) if storage_mb is not None else None,
            "storage_checked_path": str(spec.cache_dir) if phase == "load" else None,
            "storage_scope": "runtime_cache" if phase == "load" else None,
            "required_storage_mb": required_storage_mb,
            "requested_duration_seconds": request.max_duration_seconds,
            "thermal_status": thermal if isinstance(thermal, str) else "unknown",
            "captured_at": snapshot.get("captured_at"),
            "runtime_context": context,
            "limitations": [
                "RAM and storage are point-in-time observations, not guarantees.",
                "Peak RAM is estimated until measured on the target device; task budgets may override it.",
                "Android may still terminate the process under memory pressure after admission.",
            ],
        }

class LiteRTLMBackend:
    """Official LiteRT-LM Python API; one fresh conversation per Mahoraga inference."""

    MAX_STRUCTURED_MESSAGES = 32  # Keep in sync with Android ModelPromptEnvelope.MAX_MESSAGES.
    MAX_STRUCTURED_MESSAGE_CHARS = 20_000  # Android ModelPromptEnvelope.MAX_MESSAGE_CHARS.
    MAX_STRUCTURED_TOTAL_CHARS = 50_000  # Android ModelPromptEnvelope.MAX_TOTAL_CHARS.
    DEFAULT_THINKING_BUDGET = {
        "interactive": 256,
        "reasoning": 1024,
        "maintenance": 512,
        "background": 256,
    }
    DEFAULT_OUTPUT_BUDGET = {
        "interactive": 512,
        "reasoning": 1024,
        "maintenance": 768,
        "background": 512,
    }

    def __init__(self, backend_name: str = "cpu", cache_dir: Path | None = None) -> None:
        if backend_name not in {"cpu", "gpu"}:
            raise ValueError("backend_name precisa ser cpu ou gpu.")
        self.backend_name = backend_name
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else (
            Path.home() / ".cache" / "mahoraga" / "litert"
        )
        self._engine = None
        self._engine_manager = None
        self._engine_context = False
        self._litert_module = None

    def is_loaded(self) -> bool:
        return self._engine is not None

    def load(self, model_path: Path) -> None:
        if self._engine is not None:
            return
        try:
            import litert_lm  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ModelUnavailableError(
                "litert_lm indisponível. Instale o pacote oficial litert-lm-api "
                "compatível com Android ARM64."
            ) from exc

        engine = None
        try:
            backend = (
                litert_lm.Backend.GPU()
                if self.backend_name == "gpu"
                else litert_lm.Backend.CPU()
            )
            cache_dir = self.cache_dir
            cache_dir.mkdir(parents=True, exist_ok=True)
            options = {
                "backend": backend,
                "cache_dir": str(cache_dir),
            }
            engine = litert_lm.Engine(str(model_path), **options)
            enter = getattr(engine, "__enter__", None)
            if callable(enter):
                entered = enter()
                self._engine_manager = engine
                self._engine = entered if entered is not None else engine
                self._engine_context = True
            else:
                initialize = getattr(engine, "initialize", None)
                if callable(initialize):
                    initialize()
                self._engine = engine
            self._litert_module = litert_lm
        except Exception as exc:
            # Native initialization can allocate resources before raising. Do
            # not publish a half-loaded engine; make one best-effort cleanup
            # attempt when the object exposes an explicit close operation.
            if engine is not None:
                cleanup = getattr(engine, "close", None)
                if callable(cleanup):
                    try:
                        cleanup()
                    except Exception:
                        pass
            self._engine = None
            self._engine_manager = None
            self._engine_context = False
            self._litert_module = None
            raise ModelUnavailableError(
                f"LiteRT-LM não inicializou: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _structured_messages(prompt: str):
        """Decode the versioned Mahoraga envelope into LiteRT chat-template messages."""
        try:
            envelope = json.loads(prompt)
        except (TypeError, json.JSONDecodeError) as exc:
            if (
                isinstance(prompt, str)
                and prompt.lstrip().startswith("{")
                and "mahoraga_messages_v1" in prompt
            ):
                raise ModelRuntimeError(
                    "Envelope de mensagens LiteRT contém JSON inválido."
                ) from exc
            return None
        if not isinstance(envelope, dict) or envelope.get("format") != "mahoraga_messages_v1":
            return None
        messages = envelope.get("messages")
        if (
            not isinstance(messages, list)
            or not 1 <= len(messages) <= LiteRTLMBackend.MAX_STRUCTURED_MESSAGES
        ):
            raise ModelRuntimeError("Envelope de mensagens LiteRT inválido.")
        validated = []
        total_chars = 0
        for item in messages:
            if not isinstance(item, dict):
                raise ModelRuntimeError("Mensagem LiteRT inválida.")
            role = item.get("role")
            if not isinstance(role, str) or role not in {"system", "user", "assistant"}:
                raise ModelRuntimeError("Papel de mensagem LiteRT inválido.")
            content = item.get("content")
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(content) > LiteRTLMBackend.MAX_STRUCTURED_MESSAGE_CHARS
            ):
                raise ModelRuntimeError("Conteúdo de mensagem LiteRT inválido.")
            total_chars += len(content)
            if total_chars > LiteRTLMBackend.MAX_STRUCTURED_TOTAL_CHARS:
                raise ModelRuntimeError("Contexto total LiteRT excede o limite.")
            validated.append({"role": role, "content": content})
        if validated[-1]["role"] != "user":
            raise ModelRuntimeError("A última mensagem LiteRT precisa ser do usuário.")
        seen_conversation_turn = False
        for item in validated:
            if item["role"] == "system" and seen_conversation_turn:
                raise ModelRuntimeError(
                    "Mensagens system LiteRT precisam preceder o histórico da conversa."
                )
            if item["role"] != "system":
                seen_conversation_turn = True

        system_text = "\n\n".join(
            item["content"] for item in validated if item["role"] == "system"
        )
        preface = []
        if system_text:
            preface.append({
                "role": "system",
                "content": [{"type": "text", "text": system_text}],
            })
        for item in validated[:-1]:
            if item["role"] == "system":
                continue
            preface.append({
                "role": item["role"],
                "content": [{"type": "text", "text": item["content"]}],
            })
        final_message = {
            "role": "user",
            "content": [{"type": "text", "text": validated[-1]["content"]}],
        }
        return preface, final_message

    def generate(self, prompt: str, *, request: ResourceRequest) -> str:
        if self._engine is None or self._litert_module is None:
            raise ModelRuntimeError("Engine LiteRT-LM não está carregado.")
        module = self._litert_module
        thinking_budget = (
            request.thinking_token_budget
            if request.thinking_token_budget is not None
            else self.DEFAULT_THINKING_BUDGET[request.task_class]
        )
        output_budget = (
            request.max_output_tokens
            if request.max_output_tokens is not None
            else self.DEFAULT_OUTPUT_BUDGET[request.task_class]
        )
        thinking_config = module.ThinkingConfig(
            enable_thinking=thinking_budget > 0,
            thinking_token_budget=thinking_budget,
        )
        sampler_config = None
        if any(value is not None for value in (request.top_k, request.top_p, request.temperature)):
            sampler_config = module.SamplerConfig(
                top_k=request.top_k if request.top_k is not None else 20,
                top_p=request.top_p if request.top_p is not None else 0.95,
                temperature=request.temperature if request.temperature is not None else 0.6,
            )
        structured = self._structured_messages(prompt)
        conversation_options = {
            "thinking_config": thinking_config,
            "sampler_config": sampler_config,
            "automatic_tool_calling": False,
            # LiteRT-LM counts thinking tokens inside max_output_tokens.
            # Add the reserved final-answer budget so reasoning cannot consume it all.
            "max_output_tokens": thinking_budget + output_budget,
        }
        final_message = prompt
        if structured is not None:
            initial_messages, final_message = structured
            conversation_options["messages"] = initial_messages
        conversation_manager = self._engine.create_conversation(
            **conversation_options
        )
        enter_conversation = getattr(conversation_manager, "__enter__", None)
        conversation = (
            enter_conversation()
            if callable(enter_conversation)
            else conversation_manager
        )
        if conversation is None:
            conversation = conversation_manager
        timeout_seconds = request.max_duration_seconds
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
        stream = None
        output = []
        cancellation_requested = threading.Event()
        stream_finished = threading.Event()
        cancellation_lock = threading.Lock()

        def cancel_native_inference() -> None:
            # LiteRT-LM's native cancellation API is designed to interrupt the
            # active session. Each Mahoraga request owns a fresh Conversation,
            # which is closed immediately afterward (a cancelled session must
            # not be reused).
            with cancellation_lock:
                if stream_finished.is_set() or cancellation_requested.is_set():
                    return
                cancellation_requested.set()
                cancel_process = getattr(conversation, "cancel_process", None)
                if callable(cancel_process):
                    try:
                        cancel_process()
                    except Exception:
                        # Preserve the original deadline/error.
                        pass

        watchdog = None
        try:
            stream = conversation.send_message_async(final_message)
            if timeout_seconds is not None:
                watchdog = threading.Timer(timeout_seconds, cancel_native_inference)
                watchdog.daemon = True
                watchdog.start()
            for chunk in stream:
                if cancellation_requested.is_set() or (
                    deadline is not None and time.monotonic() >= deadline
                ):
                    cancel_native_inference()
                    raise ModelDeadlineExceeded("Prazo de inferência LiteRT excedido.")
                if not isinstance(chunk, dict):
                    continue
                content = chunk.get("content", [])
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        output.append(part["text"])
            if cancellation_requested.is_set():
                raise ModelDeadlineExceeded("Prazo de inferência LiteRT excedido.")
            return "".join(output)
        except Exception as exc:
            if cancellation_requested.is_set() and not isinstance(exc, ModelDeadlineExceeded):
                raise ModelDeadlineExceeded(
                    "Inferência LiteRT cancelada ao exceder o prazo."
                ) from exc
            raise
        finally:
            if deadline is not None and time.monotonic() >= deadline:
                cancel_native_inference()
            # Serialize the finished transition with a watchdog that may already
            # be entering the native cancellation call.
            with cancellation_lock:
                stream_finished.set()
            if watchdog is not None:
                watchdog.cancel()
            if cancellation_requested.is_set() and stream is not None:
                close_stream = getattr(stream, "close", None)
                if callable(close_stream):
                    close_stream()
            exit_conversation = getattr(conversation_manager, "__exit__", None)
            if callable(exit_conversation):
                exit_conversation(None, None, None)
            else:
                close_conversation = getattr(conversation, "close", None)
                if callable(close_conversation):
                    close_conversation()

    def close(self) -> None:
        engine, self._engine = self._engine, None
        manager, self._engine_manager = self._engine_manager, None
        try:
            if engine is not None:
                if self._engine_context:
                    exit_method = getattr(manager or engine, "__exit__", None)
                    if callable(exit_method):
                        exit_method(None, None, None)
                else:
                    close = getattr(engine, "close", None)
                    if callable(close):
                        close()
        finally:
            self._engine_context = False
            self._litert_module = None


class AndroidContentProviderBackend:
    """Bridge Termux Python to the app-private native LiteRT-LM owner."""

    AUTHORITY_URI = "content://com.mahoraga.runtime.model"
    CONTENT_BINARY = "/system/bin/content"

    def __init__(self, backend_name: str = "cpu", poll_interval_seconds: float = 0.25):
        if backend_name not in {"cpu", "gpu"}:
            raise ValueError("backend_name precisa ser cpu ou gpu.")
        self.backend_name = backend_name
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self._loaded = False

    @staticmethod
    def _bundle_value(output: str, key: str) -> str | None:
        match = re.search(re.escape(key) + r"=([^,\n]+)", output)
        return match.group(1).strip().rstrip("}]") if match else None

    def _call(self, method: str, arg: str | None = None,
              timeout_seconds: float = 15.0) -> str:
        command = [
            self.CONTENT_BINARY, "call", "--uri", self.AUTHORITY_URI,
            "--method", method,
        ]
        if arg is not None:
            command.extend(["--arg", arg])
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_seconds,
                check=False, encoding="utf-8",
                env={**os.environ, "PATH": "/system/bin:/system/xbin", "LC_ALL": "C.UTF-8"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ModelUnavailableError(
                f"Android model provider unavailable: {type(exc).__name__}"
            ) from exc
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode != 0:
            raise ModelUnavailableError(
                f"Android model provider call failed: exit={result.returncode}"
            )
        if "Result:" not in output:
            raise ModelUnavailableError("Android provider returned no Bundle result.")
        return output

    def _acknowledge_result(self, request_id: str) -> bool:
        """Release a terminal native result after the caller has consumed it."""
        try:
            output = self._call("ack", request_id, timeout_seconds=15.0)
        except ModelUnavailableError:
            # A lost ACK is safe: the native side retains the result until TTL.
            return False
        state = self._bundle_value(output, "status")
        return state in {"acknowledged", "already_acknowledged"}

    def cancel_request(self, request_id: str) -> str:
        """Request cancellation of exactly one native inference request."""
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id precisa ser texto não vazio.")
        output = self._call("cancel", request_id, timeout_seconds=15.0)
        state = self._bundle_value(output, "status")
        if state not in {"cancellation_requested", "already_completed", "unknown_request"}:
            raise ModelUnavailableError(
                f"Android provider returned an unknown cancellation state: {state}"
            )
        return state

    def load(self, model_path: Path) -> None:
        path = Path(model_path)
        if not path.is_file() or path.suffix.lower() != ".litertlm":
            raise ModelUnavailableError("Termux model artifact is missing or not .litertlm.")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        local_sha = digest.hexdigest()

        status = self._call("status")
        protocol_version = self._bundle_value(status, "prompt_protocol_version")
        prompt_protocol = self._bundle_value(status, "prompt_protocol")
        if protocol_version != "1" or prompt_protocol != "mahoraga_messages_v1":
            raise ModelUnavailableError(
                "Android provider prompt protocol is missing or incompatible."
            )
        imported_sha = self._bundle_value(status, "model_sha256")
        if imported_sha != local_sha:
            raise ModelUnavailableError(
                "The model imported in Mahoraga Android does not match the Termux artifact SHA-256."
            )

        output = self._call("load", self.backend_name, timeout_seconds=210.0)
        state = self._bundle_value(output, "status")
        if state == "load_pending":
            deadline = time.monotonic() + 180.0
            while time.monotonic() < deadline:
                time.sleep(self.poll_interval_seconds)
                status = self._call("status")
                lifecycle = self._bundle_value(status, "lifecycle_status")
                if lifecycle == "loaded":
                    state = "loaded"
                    break
                if lifecycle and lifecycle.startswith("load_denied"):
                    raise ModelAdmissionError(lifecycle)
                if lifecycle == "load_failed":
                    raise ModelRuntimeError("Android LiteRT engine initialization failed.")
        if state not in {"loaded", "already_loaded"}:
            raise ModelAdmissionError(f"Android model load not confirmed: {state}")
        self._loaded = True

    def is_loaded(self) -> bool:
        status = self._call("status")
        return self._bundle_value(status, "loaded") == "true"

    def generate(self, prompt: str, *, request: ResourceRequest) -> str:
        if not self._loaded:
            raise ModelRuntimeError("Android model backend is not loaded.")
        request_id = uuid.uuid4().hex
        payload = {
            "request_id": request_id,
            "prompt": prompt,
            "task_class": request.task_class,
            "max_duration_seconds": request.max_duration_seconds,
            # Android independently enforces local duration caps and derating.
            "estimated_additional_ram_mb": request.estimated_additional_ram_mb,
            "thinking_token_budget": request.thinking_token_budget,
            "max_output_tokens": request.max_output_tokens,
            "top_k": request.top_k,
            "top_p": request.top_p,
            "temperature": request.temperature,
            "allow_background": request.allow_background,
        }
        output = self._call("infer", json.dumps(payload, ensure_ascii=False), timeout_seconds=15.0)
        state = self._bundle_value(output, "status")
        if state != "accepted":
            raise ModelAdmissionError(f"Android inference request rejected: {state}")

        budget = request.max_duration_seconds or 300.0
        deadline = time.monotonic() + budget + max(30.0, budget * 0.5)
        while time.monotonic() < deadline:
            result = self._call("result", request_id, timeout_seconds=15.0)
            state = self._bundle_value(result, "status")
            if state == "pending":
                time.sleep(self.poll_interval_seconds)
                continue
            if state == "cancelled":
                self._acknowledge_result(request_id)
                raise ModelInferenceCancelled("Android inference was cancelled.")
            if state == "failed":
                error = self._bundle_value(result, "error") or "unknown"
                self._acknowledge_result(request_id)
                raise ModelRuntimeError(f"Android inference failed: {error}")
            if state == "completed":
                deadline_met = self._bundle_value(result, "deadline_met")
                if deadline_met == "false":
                    self._acknowledge_result(request_id)
                    raise ModelDeadlineExceeded(
                        "Android LiteRT stream exceeded its task duration budget."
                    )
                encoded = self._bundle_value(result, "text_b64")
                if encoded is None:
                    raise ModelRuntimeError("Android provider omitted inference output.")
                if encoded == "-":
                    self._acknowledge_result(request_id)
                    return ""
                try:
                    decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ModelRuntimeError("Android provider returned invalid text encoding.") from exc
                self._acknowledge_result(request_id)
                return decoded
            raise ModelRuntimeError(f"Unknown Android inference state: {state}")
        # The caller's wait budget expired while the native request remained pending.
        # Cancel this exact request ID, then give the provider a short bounded window
        # to publish its retained terminal outcome. Never acknowledge a pending result.
        try:
            cancellation_state = self.cancel_request(request_id)
        except ModelUnavailableError as exc:
            raise ModelDeadlineExceeded(
                "Android inference wait expired, but the cancellation request could not be "
                "delivered; native execution state is unknown and the result was not acknowledged."
            ) from exc
        if cancellation_state == "unknown_request":
            raise ModelDeadlineExceeded(
                "Android inference wait expired and the provider no longer knows this request."
            )
        terminal_deadline = time.monotonic() + 10.0
        while True:
            remaining = terminal_deadline - time.monotonic()
            if remaining <= 0:
                break
            result = self._call(
                "result", request_id, timeout_seconds=min(15.0, remaining)
            )
            terminal_state = self._bundle_value(result, "status")
            if terminal_state == "pending":
                remaining = terminal_deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(self.poll_interval_seconds, remaining))
                continue
            if terminal_state == "cancelled":
                self._acknowledge_result(request_id)
                raise ModelInferenceCancelled(
                    "Android inference was cancelled after its cooperative wait budget expired."
                )
            if terminal_state == "failed":
                error = self._bundle_value(result, "error") or "unknown"
                self._acknowledge_result(request_id)
                raise ModelRuntimeError(f"Android inference failed during cancellation: {error}")
            if terminal_state == "completed":
                self._acknowledge_result(request_id)
                raise ModelDeadlineExceeded(
                    "Android inference completed only after the caller's wait budget expired."
                )
            raise ModelRuntimeError(
                f"Unknown Android inference state after cancellation: {terminal_state}"
            )
        raise ModelDeadlineExceeded(
            "Android inference exceeded its wait budget; request-scoped cancellation was "
            f"{cancellation_state}, but no terminal result arrived within 10 seconds."
        )

    def close(self) -> None:
        try:
            self._call("unload", timeout_seconds=75.0)
        finally:
            self._loaded = False


class AdaptiveModelBackend:
    """Prefer in-process LiteRT; native Android provider fallback is explicit opt-in."""

    def __init__(
        self,
        backend_name: str = "cpu",
        cache_dir: Path | None = None,
        primary=None,
        fallback=None,
        *,
        allow_android_fallback: bool = False,
    ):
        if backend_name not in {"cpu", "gpu"}:
            raise ValueError("backend_name precisa ser cpu ou gpu.")
        self.primary = primary or LiteRTLMBackend(backend_name, cache_dir)
        if fallback is not None:
            self.fallback = fallback
        elif allow_android_fallback:
            self.fallback = AndroidContentProviderBackend(backend_name)
        else:
            self.fallback = None
        self.active = None
        self.primary_error: Exception | None = None

    def load(self, model_path: Path) -> None:
        if self.active is not None:
            health = getattr(self.active, "is_loaded", None)
            try:
                still_loaded = health() is True if callable(health) else True
            except Exception:
                still_loaded = False
            if still_loaded:
                return
            # A provider can lose its native engine while the wrapper still
            # holds an active reference. Retire that stale owner before trying
            # to load again; otherwise ModelRuntime can mark a no-op reload as
            # successful and the next generate() fails against an empty backend.
            stale, self.active = self.active, None
            closer = getattr(stale, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
        try:
            self.primary.load(model_path)
            self.active = self.primary
            self.primary_error = None
            return
        except Exception as exc:
            self.primary_error = exc

        if self.fallback is None:
            primary_name = type(self.primary_error).__name__ if self.primary_error else "unknown"
            raise ModelUnavailableError(
                "LiteRT-LM Python indisponível e fallback Android não habilitado. "
                f"Python LiteRT-LM: {primary_name}."
            ) from self.primary_error
        try:
            self.fallback.load(model_path)
            self.active = self.fallback
        except Exception as fallback_error:
            primary_name = type(self.primary_error).__name__ if self.primary_error else "unknown"
            raise ModelUnavailableError(
                "Nenhum backend local pôde carregar o modelo. "
                f"Python LiteRT-LM: {primary_name}; Android provider: "
                f"{type(fallback_error).__name__}."
            ) from fallback_error

    def is_loaded(self) -> bool:
        if self.active is None:
            return False
        health = getattr(self.active, "is_loaded", None)
        return health() if callable(health) else True

    def generate(self, prompt: str, *, request: ResourceRequest) -> str:
        if self.active is None:
            raise ModelRuntimeError("Nenhum backend local está carregado.")
        return self.active.generate(prompt, request=request)

    def close(self) -> None:
        active, self.active = self.active, None
        if active is not None:
            active.close()


class ModelRuntime:
    """Lazy, serialized model lifecycle with resource admission and audit metadata."""
    def __init__(self, spec: ModelSpec, backend: ModelBackend | None = None,
                 admission: ModelResourcePolicy | None = None, store: Any = None,
                 budget_selector=None) -> None:
        self.spec = spec
        self.backend = backend or AdaptiveModelBackend(
            self.spec.backend_name, self.spec.cache_dir
        )
        self.admission = admission
        self.store = store
        if budget_selector is None and admission is not None:
            planner = AdaptiveBudgetPlanner(
                admission.hardware,
                runtime_context_reader=admission.runtime_context_reader,
            )
            self.budget_selector = planner
        else:
            self.budget_selector = budget_selector
        self._lock = threading.RLock()
        self._loaded = False
        self._closed = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def _audit(self, event_type: str, payload: dict) -> None:
        recorder = getattr(self.store, "record_event", None)
        if callable(recorder):
            try:
                recorder(event_type, payload)
            except Exception:
                # Observability failure must not corrupt model lifecycle state.
                pass

    def verify_model_file(self) -> dict:
        path = self.spec.model_path
        if not path.is_file():
            return {"valid": False, "reason": "model_file_not_found"}
        if path.suffix.lower() != ".litertlm":
            return {"valid": False, "reason": "unexpected_model_extension"}
        size = path.stat().st_size
        if size <= 0:
            return {"valid": False, "reason": "empty_model_file"}
        if self.spec.expected_sha256:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != self.spec.expected_sha256:
                return {"valid": False, "reason": "sha256_mismatch"}
        return {"valid": True, "size_bytes": size,
                "sha256_verified": self.spec.expected_sha256 is not None}

    def _select_request(self, request: ResourceRequest | None) -> ResourceRequest:
        planner_method = getattr(self.budget_selector, "for_task", None)
        if request is not None:
            if not isinstance(request, ResourceRequest):
                raise ModelRuntimeError("request precisa ser ResourceRequest.")
            if request.max_duration_seconds is None and self.budget_selector is not None:
                if callable(planner_method):
                    planned = planner_method(
                        self.spec, request.task_class, priority=request.priority,
                        allow_background=request.allow_background,
                    )
                elif callable(self.budget_selector):
                    planned = self.budget_selector(self.spec)
                else:
                    planned = None
                if isinstance(planned, ResourceRequest):
                    return replace(
                        request,
                        max_duration_seconds=planned.max_duration_seconds,
                        duration_policy_applied=True,
                    )
            return request
        if callable(planner_method):
            selected = planner_method(self.spec, "interactive")
            if not isinstance(selected, ResourceRequest):
                raise ModelRuntimeError("budget_selector deve retornar ResourceRequest.")
            return selected
        if callable(self.budget_selector):
            selected = self.budget_selector(self.spec)
            if not isinstance(selected, ResourceRequest):
                raise ModelRuntimeError("budget_selector deve retornar ResourceRequest.")
            return selected
        return ResourceRequest()

    def load(self, request: ResourceRequest | None = None) -> dict:
        with self._lock:
            if self._closed:
                raise ModelRuntimeError("Runtime já foi encerrado.")
            if self._loaded:
                return {"loaded": True, "status": "already_loaded"}
            verified = self.verify_model_file()
            if not verified["valid"]:
                self._audit("model.load_denied", {"model_id": self.spec.model_id,
                                                  "reason": verified["reason"]})
                return {"loaded": False, **verified}
            if self.admission is None:
                return {"loaded": False, "valid": True,
                        "reason": "resource_admission_not_configured"}
            request = self._select_request(request)
            decision = self.admission.evaluate(self.spec, phase="load", request=request)
            if decision.get("allowed") is not True:
                self._audit("model.load_denied", {"model_id": self.spec.model_id,
                                                  "reason": decision.get("reason")})
                return {"loaded": False, "valid": True, "admission": decision}
            try:
                self.backend.load(self.spec.model_path)
            except Exception as exc:
                self._audit("model.load_failed", {"model_id": self.spec.model_id,
                                                  "error": type(exc).__name__})
                raise ModelRuntimeError(
                    f"Falha ao carregar modelo: {type(exc).__name__}"
                ) from exc
            self._loaded = True
            self._audit("model.loaded", {"model_id": self.spec.model_id,
                                         "size_bytes": verified["size_bytes"],
                                         "admission": decision})
            return {"loaded": True, "status": "loaded",
                    "model_id": self.spec.model_id, "admission": decision}

    def generate(self, prompt: str, *, request: ResourceRequest | None = None) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt precisa ser texto não vazio.")
        if len(prompt) > self.spec.max_prompt_chars:
            raise ValueError("prompt excede max_prompt_chars.")
        with self._lock:
            if self._closed:
                raise ModelRuntimeError("Runtime já foi encerrado.")
            request = self._select_request(request)
            thinking_budget = (
                request.thinking_token_budget
                if request.thinking_token_budget is not None
                else LiteRTLMBackend.DEFAULT_THINKING_BUDGET[request.task_class]
            )
            output_budget = (
                request.max_output_tokens
                if request.max_output_tokens is not None
                else LiteRTLMBackend.DEFAULT_OUTPUT_BUDGET[request.task_class]
            )
            estimated_input_tokens = math.ceil(len(prompt) / 3.0)
            if estimated_input_tokens + thinking_budget + output_budget > self.spec.context_window_tokens:
                raise ValueError(
                    "prompt e orçamentos de geração excedem a janela de contexto do modelo."
                )
            if not self._loaded:
                result = self.load(request=request)
                if result.get("loaded") is not True:
                    reason = result.get("reason") or result.get("admission", {}).get("reason")
                    raise ModelAdmissionError(str(reason))
            health_check = getattr(self.backend, "is_loaded", None)
            if callable(health_check):
                try:
                    backend_loaded = health_check()
                except Exception as exc:
                    self._loaded = False
                    raise ModelRuntimeError("Falha ao verificar estado do backend local.") from exc
                if backend_loaded is not True:
                    self._loaded = False
                    reload_result = self.load(request=request)
                    if reload_result.get("loaded") is not True:
                        reason = reload_result.get("reason") or reload_result.get("admission", {}).get("reason")
                        raise ModelAdmissionError(str(reason or "backend_reload_denied"))
            if self.admission is None:
                raise ModelAdmissionError("resource_admission_not_configured")
            decision = self.admission.evaluate(self.spec, phase="inference", request=request)
            if decision.get("allowed") is not True:
                reason = str(decision.get("reason"))
                if self._loaded and reason in {
                    "insufficient_available_ram", "thermal_state_blocks_model_load",
                    "foreground_state_not_confirmed", "interactive_screen_state_not_confirmed",
                }:
                    self.unload(reason=reason)
                raise ModelAdmissionError(reason)
            try:
                started = time.monotonic()
                output = self.backend.generate(
                    prompt, request=request
                )
                elapsed = time.monotonic() - started
                if (request.max_duration_seconds is not None
                        and elapsed > request.max_duration_seconds):
                    raise ModelDeadlineExceeded(
                        "Backend ultrapassou o orçamento de tempo solicitado."
                    )
            except ModelInferenceCancelled:
                self._audit("model.inference_cancelled", {
                    "model_id": self.spec.model_id,
                    "task_class": request.task_class,
                })
                raise
            except ModelDeadlineExceeded:
                self._audit("model.inference_deadline_exceeded", {
                    "model_id": self.spec.model_id,
                    "task_class": request.task_class,
                    "max_duration_seconds": request.max_duration_seconds,
                })
                raise
            except Exception as exc:
                self._audit("model.inference_failed", {"model_id": self.spec.model_id,
                                                       "error": type(exc).__name__})
                raise ModelRuntimeError(
                    f"Falha na inferência local: {type(exc).__name__}"
                ) from exc
            if not isinstance(output, str):
                raise ModelRuntimeError("Backend retornou saída que não é texto.")
            if len(output) > self.spec.max_output_chars:
                output = output[:self.spec.max_output_chars]
            self._audit("model.inference_completed", {
                "model_id": self.spec.model_id,
                "prompt_chars": len(prompt),
                "output_chars": len(output),
                "elapsed_seconds": round(elapsed, 3),
                "deadline_seconds": request.max_duration_seconds,
                "deadline_met": request.max_duration_seconds is None or elapsed <= request.max_duration_seconds,
                "admission": decision,
            })
            return output

    def unload(self, *, reason: str = "requested") -> None:
        """Release model memory while keeping the runtime eligible for later reload."""
        with self._lock:
            if not self._loaded:
                return
            try:
                self.backend.close()
            finally:
                self._loaded = False
                self._audit("model.unloaded", {
                    "model_id": self.spec.model_id,
                    "reason": reason,
                })

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self.unload(reason="runtime_closed")
            finally:
                self._closed = True
