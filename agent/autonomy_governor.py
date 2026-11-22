"""Resource-aware autonomy and initiative ranking for Mahoraga.

This module produces bounded work permits; it does not execute tools, access the
network, change Android state, install packages, or write project files.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
import time


class AutonomyGovernorError(ValueError):
    """Invalid autonomy policy input."""


class AutonomyGovernor:
    VERSION = "0.2.0"
    MIN_MEMORY_MB = 1024
    PREFERRED_MEMORY_MB = 2048
    MIN_STORAGE_MB = 1024
    PREFERRED_STORAGE_MB = 2048
    MAX_FOREGROUND_SECONDS = 5
    MAX_CHARGING_SECONDS = 20
    MAX_FOREGROUND_RAM_MB = 64
    MAX_CHARGING_RAM_MB = 256
    MAX_BATCH_TASKS = 1
    SESSION_TTL_SECONDS = 30
    MAX_ACTIVE_SESSIONS = 64
    THERMAL_STATES = {
        "normal", "light", "moderate", "severe",
        "critical", "emergency", "shutdown", "unknown",
    }

    def __init__(self, hardware, dharma):
        self.hardware = hardware
        self.dharma = dharma
        self._session_secret = secrets.token_bytes(32)
        self._session_lock = threading.Lock()
        self._active_sessions: dict[str, float] = {}

    def _session_proof(self, session: dict) -> str:
        payload = {key: value for key, value in session.items() if key != "session_proof"}
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hmac.new(self._session_secret, encoded, hashlib.sha256).hexdigest()

    def _issue_session(self, session: dict) -> dict:
        session_id = secrets.token_urlsafe(24)
        session["session_id"] = session_id
        session["issued_at_epoch"] = time.time()
        session["expires_in_seconds"] = self.SESSION_TTL_SECONDS
        session["session_proof"] = self._session_proof(session)
        now = time.monotonic()
        with self._session_lock:
            expired = [
                key for key, deadline in self._active_sessions.items()
                if deadline <= now
            ]
            for key in expired:
                self._active_sessions.pop(key, None)
            while len(self._active_sessions) >= self.MAX_ACTIVE_SESSIONS:
                self._active_sessions.pop(next(iter(self._active_sessions)), None)
            self._active_sessions[session_id] = now + self.SESSION_TTL_SECONDS
        return session

    def _verify_session(self, session: dict) -> bool:
        if not isinstance(session, dict):
            return False
        session_id = session.get("session_id")
        supplied = session.get("session_proof")
        if not isinstance(session_id, str) or not session_id or not isinstance(supplied, str):
            return False
        try:
            expected = self._session_proof(session)
        except (TypeError, ValueError, RecursionError):
            return False
        if not hmac.compare_digest(supplied, expected):
            return False
        with self._session_lock:
            deadline = self._active_sessions.get(session_id)
            if deadline is None or deadline <= time.monotonic():
                self._active_sessions.pop(session_id, None)
                return False
        return True

    def _consume_session(self, session: dict) -> bool:
        if not self._verify_session(session):
            return False
        with self._session_lock:
            deadline = self._active_sessions.get(session["session_id"])
            if deadline is None or deadline <= time.monotonic():
                self._active_sessions.pop(session["session_id"], None)
                return False
            self._active_sessions.pop(session["session_id"], None)
            return True

    @staticmethod
    def _number(value, *, minimum=0.0, maximum=1_000_000_000.0):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        if not math.isfinite(number) or not minimum <= number <= maximum:
            return None
        return number

    @staticmethod
    def _available_ram_mb(snapshot: dict) -> float | None:
        memory = snapshot.get("memory", {})
        values = memory.get("values", {}) if isinstance(memory, dict) else {}
        entry = values.get("MemAvailable", {}) if isinstance(values, dict) else {}
        if isinstance(entry, dict):
            value = AutonomyGovernor._number(entry.get("mb"), minimum=0, maximum=10_000_000)
            if value is not None:
                return value
        kb = AutonomyGovernor._number(entry.get("kb"), minimum=0, maximum=10_000_000_000) if isinstance(entry, dict) else None
        return kb / 1024 if kb is not None else None

    @staticmethod
    def _free_storage_mb(snapshot: dict) -> float | None:
        storage = snapshot.get("storage", {})
        if not isinstance(storage, dict):
            return None
        candidates = []
        for key in ("project", "termux_home", "shared_storage"):
            item = storage.get(key)
            if isinstance(item, dict):
                value = AutonomyGovernor._number(item.get("free_bytes"), minimum=0, maximum=10**18)
                if value is not None:
                    candidates.append(value / (1024 * 1024))
        return min(candidates) if candidates else None

    @staticmethod
    def _battery_data(snapshot: dict) -> dict:
        battery = snapshot.get("battery", {})
        if not isinstance(battery, dict):
            return {}
        api = battery.get("termux_api", {})
        data = api.get("data", {}) if isinstance(api, dict) else {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def _battery_level(cls, snapshot: dict) -> float | None:
        data = cls._battery_data(snapshot)
        value = cls._number(data.get("percentage"), minimum=0, maximum=100)
        if value is not None:
            return value
        battery = snapshot.get("battery", {})
        sysfs = battery.get("sysfs_read_only", {}) if isinstance(battery, dict) else {}
        return cls._number(sysfs.get("capacity"), minimum=0, maximum=100) if isinstance(sysfs, dict) else None

    @classmethod
    def _charging_state(cls, snapshot: dict) -> bool | None:
        data = cls._battery_data(snapshot)
        status = data.get("status")
        if isinstance(status, str):
            normalized = status.strip().casefold()
            if normalized in {"charging", "full"}:
                return True
            if normalized in {"discharging", "not charging", "unplugged"}:
                return False
        battery = snapshot.get("battery", {})
        sysfs = battery.get("sysfs_read_only", {}) if isinstance(battery, dict) else {}
        status = sysfs.get("status") if isinstance(sysfs, dict) else None
        if isinstance(status, str):
            normalized = status.strip().casefold()
            if normalized in {"charging", "full"}:
                return True
            if normalized in {"discharging", "not charging"}:
                return False
        return None

    def _read_resources(self) -> dict:
        return {
            "battery": self.hardware.battery(),
            "memory": self.hardware.memory(),
            "storage": self.hardware.storage(),
            "thermal": self.hardware.thermal(),
        }

    def evaluate_session(
        self,
        runtime_context: dict | None = None,
        *,
        resource_snapshot: dict | None = None,
    ) -> dict:
        """Evaluate one bounded foreground window; unavailable context pauses work."""
        decision = self.dharma.evaluate("inspect_hardware")
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if runtime_context is None:
            reader = getattr(self.hardware, "runtime_context", None)
            runtime_context = (
                reader() if callable(reader)
                else {
                    "app_foreground": None,
                    "screen_interactive": None,
                    "thermal_status": "unknown",
                    "status": "runtime_context_unavailable",
                    "source": "none",
                }
            )
        if not isinstance(runtime_context, dict):
            raise AutonomyGovernorError("runtime_context precisa ser um objeto ou None.")
        for flag in ("app_foreground", "screen_interactive"):
            value = runtime_context.get(flag)
            if value is not None and not isinstance(value, bool):
                raise AutonomyGovernorError(
                    f"runtime_context.{flag} precisa ser booleano ou None."
                )

        snapshot = resource_snapshot if resource_snapshot is not None else self._read_resources()
        if not isinstance(snapshot, dict):
            raise AutonomyGovernorError("resource_snapshot precisa ser um objeto.")

        battery_level = self._battery_level(snapshot)
        charging = runtime_context.get("charging")
        if charging is not None and not isinstance(charging, bool):
            raise AutonomyGovernorError("charging precisa ser booleano ou None.")
        if charging is None:
            charging = self._charging_state(snapshot)

        thermal_status = runtime_context.get("thermal_status", "unknown")
        if not isinstance(thermal_status, str):
            raise AutonomyGovernorError("thermal_status precisa ser texto.")
        thermal_status = thermal_status.strip().casefold()
        if thermal_status not in self.THERMAL_STATES:
            raise AutonomyGovernorError("thermal_status não reconhecido.")

        ram_mb = self._available_ram_mb(snapshot)
        storage_mb = self._free_storage_mb(snapshot)
        foreground = runtime_context.get("app_foreground")
        interactive = runtime_context.get("screen_interactive")

        reasons = []
        if foreground is None:
            reasons.append("app_foreground_unknown")
        elif foreground is False:
            reasons.append("app_not_foreground")
        if interactive is None:
            reasons.append("screen_interactive_unknown")
        elif interactive is False:
            reasons.append("screen_not_interactive")
        if foreground is not True or interactive is not True:
            mode = (
                "runtime_context_unknown"
                if foreground is None or interactive is None
                else "deferred_background"
            )
            max_seconds = 0
            max_ram_mb = 0
        elif thermal_status in {"severe", "critical", "emergency", "shutdown"}:
            reasons.append("thermal_state_blocks_local_work")
            mode = "thermal_pause"
            max_seconds = 0
            max_ram_mb = 0
        elif ram_mb is None or ram_mb < self.MIN_MEMORY_MB:
            reasons.append("available_memory_unknown_or_below_minimum")
            mode = "resource_pause"
            max_seconds = 0
            max_ram_mb = 0
        elif storage_mb is None or storage_mb < self.MIN_STORAGE_MB:
            reasons.append("free_storage_unknown_or_below_minimum")
            mode = "resource_pause"
            max_seconds = 0
            max_ram_mb = 0
        elif charging is True:
            mode = "foreground_charging"
            max_seconds = self.MAX_CHARGING_SECONDS
            max_ram_mb = self.MAX_CHARGING_RAM_MB
            if thermal_status == "moderate":
                max_seconds = min(max_seconds, 8)
                max_ram_mb = min(max_ram_mb, 96)
                reasons.append("thermal_moderate_reduced_budget")
            elif thermal_status == "unknown":
                max_seconds = min(max_seconds, 5)
                max_ram_mb = min(max_ram_mb, 64)
                reasons.append("thermal_unknown_reduced_budget")
            if ram_mb < self.PREFERRED_MEMORY_MB:
                max_seconds = min(max_seconds, 8)
                max_ram_mb = min(max_ram_mb, 96)
                reasons.append("memory_headroom_reduced_budget")
            if storage_mb < self.PREFERRED_STORAGE_MB:
                max_seconds = min(max_seconds, 8)
                max_ram_mb = min(max_ram_mb, 96)
                reasons.append("storage_headroom_reduced_budget")
        else:
            mode = "foreground_light"
            max_seconds = self.MAX_FOREGROUND_SECONDS
            max_ram_mb = self.MAX_FOREGROUND_RAM_MB
            if thermal_status == "unknown":
                max_seconds = min(max_seconds, 2)
                reasons.append("thermal_unknown_limited_to_brief_work")
            if charging is None:
                reasons.append("charging_state_unknown_light_budget_only")
            if battery_level is not None and battery_level < 20:
                max_seconds = min(max_seconds, 1)
                reasons.append("low_battery_reduced_budget")

        session = {
            "component": "AutonomyGovernor",
            "version": self.VERSION,
            "status": "paused" if max_seconds == 0 else "bounded",
            "mode": mode,
            "runtime_context": {
                "app_foreground": foreground,
                "screen_interactive": interactive,
                "charging": charging,
                "thermal_status": thermal_status,
                "source": runtime_context.get("source"),
                "context_status": runtime_context.get("status"),
            },
            "resources": {
                "battery_percentage": battery_level,
                "available_ram_mb": round(ram_mb, 2) if ram_mb is not None else None,
                "free_storage_mb": round(storage_mb, 2) if storage_mb is not None else None,
            },
            "budget": {
                "max_task_seconds": max_seconds,
                "max_task_ram_mb": max_ram_mb,
                "max_concurrent_tasks": self.MAX_BATCH_TASKS if max_seconds else 0,
                "continuous_loop_allowed": False,
                "network_allowed": False,
                "camera_capture_allowed": False,
                "microphone_capture_allowed": False,
                "android_changes_allowed": False,
                "package_installation_allowed": False,
                "project_writes_allowed": False,
            },
            "reasons": reasons or ["foreground_resource_budget_available"],
            "assumptions": [
                "Foreground and interactive-screen state is read from the fixed Shizuku/rish adapter when omitted; unavailable or unknown state pauses work.",
                "Charging may be derived from Termux:API/sysfs only when an explicit runtime value is absent.",
                "Thermal status remains unknown unless a trusted runtime source supplies a normalized state.",
                "This is a per-task budget, not a promise of sustained background execution.",
            ],
        }
        return self._issue_session(session)

    def evaluate_work(
        self,
        session: dict,
        work_request: dict,
    ) -> dict:
        """Return a permit decision for one bounded, local, reversible task."""
        if not isinstance(session, dict) or not isinstance(work_request, dict):
            raise AutonomyGovernorError("session e work_request precisam ser objetos.")
        if not self._verify_session(session):
            return {
                "allowed": False,
                "reason": "session_invalid_expired_or_already_consumed",
                "permit": None,
            }
        budget = session.get("budget")
        if not isinstance(budget, dict):
            return {"allowed": False, "reason": "session_budget_invalid", "permit": None}
        risk = work_request.get("risk")
        if not isinstance(risk, str) or risk not in {"read_only", "local_compute"}:
            return {"allowed": False, "reason": "risk_not_allowlisted", "permit": None}
        forbidden = (
            "requires_network", "requires_camera", "requires_microphone",
            "writes_project", "installs_packages", "changes_android",
            "captures_sensitive_data", "persistent_external_change",
            "requires_audio_output",
        )
        for key in forbidden:
            value = work_request.get(key, False)
            if not isinstance(value, bool):
                raise AutonomyGovernorError(f"{key} precisa ser booleano.")
        raised = [key for key in forbidden if work_request.get(key, False) is True]
        if raised:
            return {
                "allowed": False,
                "reason": "work_exceeds_initial_autonomy_scope",
                "blocked_requirements": raised,
                "permit": None,
            }
        if session.get("status") != "bounded":
            return {"allowed": False, "reason": "session_not_permitted", "permit": None}

        estimated_seconds = self._number(
            work_request.get("estimated_seconds"), minimum=0.01, maximum=3600
        )
        estimated_ram = self._number(
            work_request.get("estimated_ram_mb"), minimum=1, maximum=1_000_000
        )
        if estimated_seconds is None or estimated_ram is None:
            raise AutonomyGovernorError("Estimativas de tempo e RAM precisam ser válidas.")
        if estimated_seconds > budget["max_task_seconds"]:
            return {"allowed": False, "reason": "task_exceeds_time_budget", "permit": None}
        if estimated_ram > budget["max_task_ram_mb"]:
            return {"allowed": False, "reason": "task_exceeds_memory_budget", "permit": None}

        authorization = self.dharma.evaluate(
            "read_only_capability" if risk == "read_only" else "local_compute"
        )
        if not authorization.allowed:
            return {
                "allowed": False,
                "reason": "dharma_denied",
                "authorization_reason": authorization.reason,
                "permit": None,
            }
        if not self._consume_session(session):
            return {
                "allowed": False,
                "reason": "session_invalid_expired_or_already_consumed",
                "permit": None,
            }
        return {
            "allowed": True,
            "reason": "bounded_local_work_permitted",
            "permit": {
                "task_id": str(work_request.get("task_id", "unnamed"))[:120],
                "risk": risk,
                "max_runtime_seconds": float(estimated_seconds),
                "max_memory_mb": float(estimated_ram),
                "continuous_loop": False,
                "side_effects": "none",
                "dharma_category": authorization.category,
                "execution_performed": False,
            },
        }

    def rank_initiatives(self, candidates: list[dict]) -> dict:
        """Prioritize learnable progress over raw novelty; this does not adopt work."""
        if not isinstance(candidates, list):
            raise AutonomyGovernorError("candidates precisa ser uma lista.")
        if len(candidates) > 200:
            raise AutonomyGovernorError("A revisão aceita no máximo 200 candidatos.")

        ranked = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence", {})
            if not isinstance(evidence, dict):
                evidence = {}
            priority = item.get("priority", "normal")
            priority_score = {"low": 0.25, "normal": 0.5, "high": 0.75, "critical": 1.0}.get(priority, 0.5)
            progress = self._number(evidence.get("learning_progress"), minimum=0, maximum=1) or 0.0
            reducible = self._number(evidence.get("uncertainty_reducible"), minimum=0, maximum=1) or 0.0
            novelty = self._number(evidence.get("novelty"), minimum=0, maximum=1) or 0.0
            regression = self._number(
                evidence.get("prediction_regression"), minimum=0, maximum=1
            ) or 0.0
            episodes = self._number(evidence.get("episode_count"), minimum=0, maximum=10_000) or 0.0
            validated = self._number(evidence.get("validated_episode_count"), minimum=0, maximum=10_000) or 0.0
            # Caller-reported validation is deliberately discounted until source
            # independence and evidence are checked by a separate evaluator.
            episode_signal = min(episodes / 5.0, 1.0) * 0.5
            validation_signal = min(validated / 5.0, 1.0) * 0.1
            source_independence_claimed = evidence.get("source_independence_verified") is True
            # A candidate payload cannot authenticate its own source independence.
            # Until a separate verifier exists, all caller claims remain unverified.
            source_independent = False
            evidence_score = min(1.0, episode_signal + validation_signal)
            if not source_independent:
                evidence_score *= 0.5
            components = {
                "priority": priority_score,
                "learning_progress": progress,
                "reducible_uncertainty": reducible,
                "evidence_quality": evidence_score,
                "novelty": novelty,
                "prediction_regression": regression,
                "source_independence_verified": False,
                "source_independence_claimed": source_independence_claimed,
            }
            base_score = (
                0.15 * priority_score
                + 0.35 * progress
                + 0.25 * reducible
                + 0.20 * evidence_score
                + 0.05 * novelty
            )
            score = max(0.0, min(1.0, base_score - 0.10 * regression))
            ranked.append({
                "candidate_id": item.get("candidate_id"),
                "title": item.get("title"),
                "kind": item.get("kind"),
                "score": round(score, 6),
                "components": components,
                "epistemic_note": (
                    "Independência das fontes não confirmada; declaração do candidato ignorada até verificação externa."
                ),
            })
        ranked.sort(key=lambda item: (-item["score"], str(item["candidate_id"] or "")))
        return {
            "status": "ranked",
            "candidate_count": len(ranked),
            "automatic_adoption": False,
            "automatic_goal_creation": False,
            "automatic_learning_consolidation": False,
            "automatic_tool_dispatch": False,
            "ranking": ranked,
        }
