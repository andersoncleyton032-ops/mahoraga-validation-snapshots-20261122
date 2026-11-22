"""Persistent one-shot queue for Mahoraga's background work.

Queue state is stored in the canonical KnowledgeStore memory table. Each
compare-and-set update and its audit event commit in one SQLite transaction.
This module does not create timers, threads, Android services or a work loop:
a platform worker must call BackgroundWorkScheduler.run_once().
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from agent.store import MemoryVersionConflict


class BackgroundWorkQueueError(ValueError):
    """Invalid queue descriptor or persisted state."""


class BackgroundWorkQueueConflict(RuntimeError):
    """Concurrent queue update; retry in a later worker invocation."""


class PersistentBackgroundWorkQueue:
    VERSION = "0.1.0"
    MEMORY_KEY = "background_work_queue.v1"
    EVENT_TYPE = "background.work.queue.transition"
    SCHEMA = "mahoraga.background_work_queue"
    MAX_ACTIVE_ITEMS = 250
    MAX_DESCRIPTOR_BYTES = 8192
    MAX_RECENT_FINISHED = 256
    MIN_LEASE_SECONDS = 15
    MAX_LEASE_SECONDS = 600
    PRIORITY = {"low": 0, "normal": 1, "high": 2}

    def __init__(self, store):
        if store is None or not callable(getattr(store, "get_memory", None)):
            raise BackgroundWorkQueueError("store precisa ser um KnowledgeStore compatível.")
        if not callable(getattr(store, "compare_and_set_memory_with_event", None)):
            raise BackgroundWorkQueueError("store não oferece memória versionada atômica.")
        self.store = store

    @staticmethod
    def _now(value=None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise BackgroundWorkQueueError("Horário precisa ser ISO-8601 válido.") from exc
        else:
            raise BackgroundWorkQueueError("Horário precisa ser datetime, ISO-8601 ou None.")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise BackgroundWorkQueueError("Horário precisa conter fuso horário.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _text(value, name: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise BackgroundWorkQueueError(f"{name} precisa conter de 1 a {maximum} caracteres.")
        return value.strip()

    @staticmethod
    def _bounded_number(value, name: str, maximum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BackgroundWorkQueueError(f"{name} precisa ser numérico.")
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise BackgroundWorkQueueError(f"{name} inválido.") from exc
        if not math.isfinite(number) or number <= 0 or number > maximum:
            raise BackgroundWorkQueueError(f"{name} fora do limite permitido.")
        return number

    def _validate_descriptor(self, task: dict, now: datetime) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise BackgroundWorkQueueError("task precisa ser um dicionário.")
        allowed = {
            "task_id", "name", "capability", "args", "kwargs", "risk",
            "estimated_runtime_seconds", "estimated_ram_mb", "checkpointable",
            "priority", "max_attempts",
        }
        unknown = set(task) - allowed
        if unknown:
            raise BackgroundWorkQueueError(
                "Descritor contém campos não permitidos: " + ", ".join(sorted(unknown))
            )

        task_id = self._text(task.get("task_id"), "task_id", 160)
        name = self._text(task.get("name"), "name", 120)
        capability = self._text(task.get("capability"), "capability", 160)
        risk = task.get("risk")
        if not isinstance(risk, str) or risk not in {"read_only", "local_compute"}:
            raise BackgroundWorkQueueError("risk precisa ser read_only ou local_compute.")
        args = task.get("args", [])
        kwargs = task.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            raise BackgroundWorkQueueError("args precisa ser lista e kwargs precisa ser objeto.")
        if task.get("checkpointable") is not True:
            raise BackgroundWorkQueueError("Trabalho de background precisa ser checkpointable.")
        priority = task.get("priority", "normal")
        if not isinstance(priority, str) or priority not in self.PRIORITY:
            raise BackgroundWorkQueueError("priority precisa ser low, normal ou high.")
        max_attempts = task.get("max_attempts", 3)
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 5
        ):
            raise BackgroundWorkQueueError("max_attempts precisa ser inteiro entre 1 e 5.")

        descriptor = {
            "task_id": task_id,
            "name": name,
            "capability": capability,
            "args": args,
            "kwargs": kwargs,
            "risk": risk,
            "estimated_runtime_seconds": self._bounded_number(
                task.get("estimated_runtime_seconds"), "estimated_runtime_seconds", 20.0
            ),
            "estimated_ram_mb": self._bounded_number(
                task.get("estimated_ram_mb"), "estimated_ram_mb", 128.0
            ),
            "checkpointable": True,
            "priority": priority,
            "max_attempts": max_attempts,
            "created_at": now.isoformat(timespec="microseconds"),
        }
        try:
            encoded = json.dumps(
                descriptor, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise BackgroundWorkQueueError("Descritor de tarefa não é JSON válido.") from exc
        if len(encoded) > self.MAX_DESCRIPTOR_BYTES:
            raise BackgroundWorkQueueError("Descritor excede 8192 bytes.")
        return descriptor

    def _read(self) -> dict[str, Any]:
        entry = self.store.get_memory(self.MEMORY_KEY)
        if entry is None:
            return {"revision": 0, "items": {}, "recently_finished": []}
        value = entry.get("value") if isinstance(entry, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("schema") != self.SCHEMA
            or isinstance(value.get("schema_version"), bool)
            or value.get("schema_version") != 1
            or isinstance(value.get("revision"), bool)
            or not isinstance(value.get("revision"), int)
            or value.get("revision") < 1
            or not isinstance(value.get("items"), dict)
            or not isinstance(value.get("recently_finished"), list)
        ):
            raise BackgroundWorkQueueError("Estado persistido da fila inválido; operação bloqueada.")
        if len(value["items"]) > self.MAX_ACTIVE_ITEMS:
            raise BackgroundWorkQueueError("Estado persistido excede o limite de itens ativos.")
        if len(value["recently_finished"]) > self.MAX_RECENT_FINISHED:
            raise BackgroundWorkQueueError("Histórico recente da fila excede o limite.")
        for task_id, item in value["items"].items():
            if (
                not isinstance(task_id, str)
                or not isinstance(item, dict)
                or item.get("task_id") != task_id
                or not isinstance(item.get("status"), str)
                or item.get("status") not in {"queued", "claimed"}
                or isinstance(item.get("attempts"), bool)
                or not isinstance(item.get("attempts"), int)
                or item.get("attempts") < 0
                or isinstance(item.get("max_attempts"), bool)
                or not isinstance(item.get("max_attempts"), int)
                or not 1 <= item.get("max_attempts") <= 5
                or item.get("attempts") > item.get("max_attempts")
                or not isinstance(item.get("priority"), str)
                or item.get("priority") not in self.PRIORITY
                or not isinstance(item.get("risk"), str)
                or item.get("risk") not in {"read_only", "local_compute"}
                or item.get("checkpointable") is not True
                or not isinstance(item.get("args"), list)
                or not isinstance(item.get("kwargs"), dict)
                or not isinstance(item.get("name"), str)
                or not item.get("name", "").strip()
                or not isinstance(item.get("capability"), str)
                or not item.get("capability", "").strip()
            ):
                raise BackgroundWorkQueueError("Item persistido da fila inválido.")
            self._now(item.get("created_at"))
            if item["status"] == "claimed":
                self._text(item.get("worker_id"), "worker_id", 80)
                self._now(item.get("lease_until"))
            elif item.get("worker_id") is not None or item.get("lease_until") is not None:
                raise BackgroundWorkQueueError("Item queued contém lease inconsistente.")
            self._bounded_number(
                item.get("estimated_runtime_seconds"), "estimated_runtime_seconds", 20.0
            )
            self._bounded_number(item.get("estimated_ram_mb"), "estimated_ram_mb", 128.0)
        return {
            "revision": value["revision"],
            "items": {key: dict(item) for key, item in value["items"].items()},
            "recently_finished": list(value["recently_finished"]),
        }

    def _commit(
        self,
        snapshot: dict,
        operation: str,
        task_id: str | None,
        *,
        details: dict | None = None,
    ) -> int:
        value = {
            "schema": self.SCHEMA,
            "schema_version": 1,
            "items": snapshot["items"],
            "recently_finished": snapshot["recently_finished"],
        }
        payload = {"operation": operation, "task_id": task_id, "details": details or {}}
        try:
            result = self.store.compare_and_set_memory_with_event(
                self.MEMORY_KEY,
                snapshot["revision"],
                value,
                self.EVENT_TYPE,
                payload,
                metadata={"kind": "persistent_background_work_queue", "version": self.VERSION},
            )
        except MemoryVersionConflict as exc:
            raise BackgroundWorkQueueConflict(str(exc)) from exc
        return result["revision"]

    def enqueue(self, task: dict, *, now=None) -> dict[str, Any]:
        timestamp = self._now(now)
        descriptor = self._validate_descriptor(task, timestamp)
        snapshot = self._read()
        task_id = descriptor["task_id"]
        existing = snapshot["items"].get(task_id)
        if existing is not None:
            immutable_fields = (
                "name", "capability", "args", "kwargs", "risk",
                "estimated_runtime_seconds", "estimated_ram_mb",
                "checkpointable", "priority", "max_attempts",
            )
            if any(existing.get(field) != descriptor.get(field) for field in immutable_fields):
                raise BackgroundWorkQueueConflict(
                    "task_id já existe com um descritor diferente."
                )
            return {
                "status": "already_known",
                "task_id": task_id,
                "item": existing,
                "revision": snapshot["revision"],
            }
        if any(
            isinstance(done, dict) and done.get("task_id") == task_id
            for done in snapshot["recently_finished"]
        ):
            return {
                "status": "already_known",
                "task_id": task_id,
                "item": None,
                "revision": snapshot["revision"],
            }
        if len(snapshot["items"]) >= self.MAX_ACTIVE_ITEMS:
            raise BackgroundWorkQueueError("Fila atingiu o limite de itens ativos.")
        item = {
            **descriptor,
            "status": "queued",
            "attempts": 0,
            "worker_id": None,
            "lease_until": None,
            "last_error": None,
        }
        snapshot["items"][task_id] = item
        try:
            revision = self._commit(
                snapshot, "enqueued", task_id,
                details={"priority": item["priority"], "capability": item["capability"]},
            )
        except BackgroundWorkQueueConflict:
            latest = self._read()
            concurrent_item = latest["items"].get(task_id)
            if concurrent_item is not None:
                immutable_fields = (
                    "name", "capability", "args", "kwargs", "risk",
                    "estimated_runtime_seconds", "estimated_ram_mb",
                    "checkpointable", "priority", "max_attempts",
                )
                if any(
                    concurrent_item.get(field) != descriptor.get(field)
                    for field in immutable_fields
                ):
                    raise BackgroundWorkQueueConflict(
                        "task_id concorrente foi usado com descritor diferente."
                    )
                return {
                    "status": "already_known",
                    "task_id": task_id,
                    "item": concurrent_item,
                    "revision": latest["revision"],
                }
            if any(
                isinstance(done, dict) and done.get("task_id") == task_id
                for done in latest["recently_finished"]
            ):
                return {
                    "status": "already_known",
                    "task_id": task_id,
                    "item": None,
                    "revision": latest["revision"],
                }
            raise
        return {"status": "enqueued", "task_id": task_id, "item": dict(item), "revision": revision}

    def _remember_finished(self, snapshot: dict, task_id: str, status: str, reason: str | None):
        snapshot["items"].pop(task_id, None)
        snapshot["recently_finished"].append({
            "task_id": task_id,
            "status": status,
            "reason": reason,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        })
        snapshot["recently_finished"] = snapshot["recently_finished"][-self.MAX_RECENT_FINISHED:]

    def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 90,
        now=None,
    ) -> dict[str, Any] | None:
        worker = self._text(worker_id, "worker_id", 80)
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or not self.MIN_LEASE_SECONDS <= lease_seconds <= self.MAX_LEASE_SECONDS
        ):
            raise BackgroundWorkQueueError("lease_seconds precisa estar entre 15 e 600.")
        timestamp = self._now(now)
        snapshot = self._read()
        candidates = []
        reaped = []
        for task_id, item in list(snapshot["items"].items()):
            expired = (
                item["status"] == "claimed"
                and self._now(item["lease_until"]) <= timestamp
            )
            exhausted = item["attempts"] >= item["max_attempts"]
            if exhausted and (item["status"] == "queued" or expired):
                self._remember_finished(
                    snapshot, task_id, "failed", "maximum_attempts_or_lease_exhausted"
                )
                reaped.append(task_id)
                continue
            if item["status"] == "queued" or expired:
                candidates.append(item)
        if not candidates:
            if reaped:
                self._commit(
                    snapshot, "reaped_exhausted", None,
                    details={"task_ids": reaped},
                )
            return None
        candidates.sort(
            key=lambda item: (
                -self.PRIORITY[item["priority"]],
                item["created_at"],
                item["task_id"],
            )
        )
        selected = dict(candidates[0])
        selected["status"] = "claimed"
        selected["attempts"] += 1
        selected["worker_id"] = worker
        selected["lease_until"] = (
            timestamp + timedelta(seconds=lease_seconds)
        ).isoformat(timespec="microseconds")
        snapshot["items"][selected["task_id"]] = selected
        revision = self._commit(
            snapshot, "claimed", selected["task_id"],
            details={
                "worker_id": worker,
                "attempt": selected["attempts"],
                "lease_until": selected["lease_until"],
                "reaped_task_ids": reaped,
            },
        )
        return {**selected, "queue_revision": revision}

    def _claimed_item(self, snapshot: dict, task_id: str, worker_id: str) -> dict:
        item = snapshot["items"].get(task_id)
        if (
            not isinstance(item, dict)
            or item.get("status") != "claimed"
            or item.get("worker_id") != worker_id
        ):
            raise BackgroundWorkQueueConflict("Tarefa não está reservada por este worker.")
        return item

    def release(
        self,
        task_id: str,
        worker_id: str,
        *,
        reason: str,
        count_attempt: bool = False,
    ) -> dict[str, Any]:
        task = self._text(task_id, "task_id", 160)
        worker = self._text(worker_id, "worker_id", 80)
        why = self._text(reason, "reason", 240)
        if not isinstance(count_attempt, bool):
            raise BackgroundWorkQueueError("count_attempt precisa ser booleano.")
        snapshot = self._read()
        item = dict(self._claimed_item(snapshot, task, worker))
        if not count_attempt:
            item["attempts"] = max(0, item["attempts"] - 1)
        item.update({
            "status": "queued",
            "worker_id": None,
            "lease_until": None,
            "last_error": why,
        })
        snapshot["items"][task] = item
        revision = self._commit(
            snapshot, "released", task,
            details={"worker_id": worker, "reason": why, "attempts": item["attempts"]},
        )
        return {"status": "queued", "task_id": task, "revision": revision}

    def complete(self, task_id: str, worker_id: str, *, summary: str = "completed") -> dict[str, Any]:
        task = self._text(task_id, "task_id", 160)
        worker = self._text(worker_id, "worker_id", 80)
        note = self._text(summary, "summary", 240)
        snapshot = self._read()
        self._claimed_item(snapshot, task, worker)
        self._remember_finished(snapshot, task, "completed", note)
        revision = self._commit(
            snapshot, "completed", task,
            details={"worker_id": worker, "summary": note},
        )
        return {"status": "completed", "task_id": task, "revision": revision}

    def fail(self, task_id: str, worker_id: str, *, reason: str) -> dict[str, Any]:
        """Terminally reject an invalid or incompatible queued task."""
        task = self._text(task_id, "task_id", 160)
        worker = self._text(worker_id, "worker_id", 80)
        why = self._text(reason, "reason", 240)
        snapshot = self._read()
        self._claimed_item(snapshot, task, worker)
        self._remember_finished(snapshot, task, "failed", why)
        revision = self._commit(
            snapshot, "failed", task,
            details={"worker_id": worker, "reason": why, "terminal": True},
        )
        return {"status": "failed", "task_id": task, "revision": revision}

    def retry(self, task_id: str, worker_id: str, *, reason: str) -> dict[str, Any]:
        task = self._text(task_id, "task_id", 160)
        worker = self._text(worker_id, "worker_id", 80)
        why = self._text(reason, "reason", 240)
        snapshot = self._read()
        item = dict(self._claimed_item(snapshot, task, worker))
        if item["attempts"] >= item["max_attempts"]:
            self._remember_finished(snapshot, task, "failed", why)
            status = "failed"
        else:
            item.update({
                "status": "queued",
                "worker_id": None,
                "lease_until": None,
                "last_error": why,
            })
            snapshot["items"][task] = item
            status = "queued"
        revision = self._commit(
            snapshot, "retry" if status == "queued" else "failed", task,
            details={"worker_id": worker, "reason": why, "status": status},
        )
        return {"status": status, "task_id": task, "revision": revision}

    def list_items(self) -> list[dict[str, Any]]:
        snapshot = self._read()
        return sorted(
            (dict(item) for item in snapshot["items"].values()),
            key=lambda item: (
                -self.PRIORITY[item["priority"]],
                item["created_at"],
                item["task_id"],
            ),
        )

    def has_pending(self, *, now=None) -> bool:
        timestamp = self._now(now)
        for item in self._read()["items"].values():
            if item["status"] == "queued" and item["attempts"] < item["max_attempts"]:
                return True
            if item["status"] == "claimed" and item["attempts"] < item["max_attempts"]:
                if self._now(item["lease_until"]) <= timestamp:
                    return True
        return False

    def summary(self) -> dict[str, Any]:
        snapshot = self._read()
        items = list(snapshot["items"].values())
        return {
            "component": "PersistentBackgroundWorkQueue",
            "version": self.VERSION,
            "revision": snapshot["revision"],
            "queued": sum(item["status"] == "queued" for item in items),
            "claimed": sum(item["status"] == "claimed" for item in items),
            "active_items": len(items),
            "recently_finished": len(snapshot["recently_finished"]),
            "pending": self.has_pending(),
            "execution_performed": False,
        }


class BackgroundWorkScheduler:
    """Execute at most one queued task per platform-triggered invocation."""

    VERSION = "0.1.0"
    MIN_NEXT_TASK_DELAY_SECONDS = 60

    def __init__(self, queue: PersistentBackgroundWorkQueue, orchestrator, worker_id: str, wake_adapter=None):
        if not isinstance(queue, PersistentBackgroundWorkQueue):
            raise BackgroundWorkQueueError("queue precisa ser PersistentBackgroundWorkQueue.")
        if not callable(getattr(orchestrator, "run_parallel", None)):
            raise BackgroundWorkQueueError("orchestrator precisa oferecer run_parallel().")
        self.queue = queue
        self.orchestrator = orchestrator
        self.worker_id = PersistentBackgroundWorkQueue._text(worker_id, "worker_id", 80)
        self.wake_adapter = wake_adapter

    def _schedule_next(self, delay_seconds: int) -> dict[str, Any]:
        if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int) or not 0 <= delay_seconds <= 3600:
            return {"status": "invalid_delay", "delay_seconds": None}
        if not self.queue.has_pending():
            return {"status": "not_needed", "delay_seconds": None}
        schedule = getattr(self.wake_adapter, "schedule_next", None)
        if not callable(schedule):
            return {"status": "adapter_missing", "delay_seconds": None}
        try:
            result = schedule(delay_seconds=delay_seconds)
        except Exception:
            return {"status": "adapter_error", "delay_seconds": delay_seconds}
        if result is not True:
            return {"status": "adapter_rejected", "delay_seconds": delay_seconds}
        return {"status": "scheduled", "delay_seconds": delay_seconds}

    def run_once(
        self,
        runtime_context: dict | None,
        *,
        resource_snapshot: dict | None = None,
    ) -> dict[str, Any]:
        """Claim, execute, checkpoint and return; never loops inside the process."""
        item = self.queue.claim_next(self.worker_id)
        if item is None:
            return {
                "status": "idle",
                "task_id": None,
                "execution_performed": False,
                "wake_schedule": {"status": "not_needed", "delay_seconds": None},
            }

        if not isinstance(runtime_context, dict):
            self.queue.release(
                item["task_id"], self.worker_id,
                reason="runtime_context_unknown",
                count_attempt=False,
            )
            return {
                "status": "deferred",
                "task_id": item["task_id"],
                "reason": "runtime_context_unknown",
                "execution_performed": False,
                "wake_schedule": self._schedule_next(900),
            }
        if runtime_context.get("app_foreground") is not False:
            self.queue.release(
                item["task_id"], self.worker_id,
                reason="mahoraga_app_not_confirmed_background",
                count_attempt=False,
            )
            return {
                "status": "deferred",
                "task_id": item["task_id"],
                "reason": "mahoraga_app_not_confirmed_background",
                "execution_performed": False,
                "wake_schedule": self._schedule_next(900),
            }
        screen_interactive = runtime_context.get("screen_interactive")
        if not isinstance(screen_interactive, bool):
            self.queue.release(
                item["task_id"], self.worker_id,
                reason="screen_interactive_state_unknown",
                count_attempt=False,
            )
            return {
                "status": "deferred",
                "task_id": item["task_id"],
                "reason": "screen_interactive_state_unknown",
                "execution_performed": False,
                "wake_schedule": self._schedule_next(900),
            }
        work_mode = (
            "background_companion" if screen_interactive else "background_idle"
        )

        capability_reader = getattr(self.orchestrator, "capability_descriptor", None)
        if callable(capability_reader):
            capability = capability_reader(item["capability"])
            if not isinstance(capability, dict):
                rejected = self.queue.fail(
                    item["task_id"], self.worker_id,
                    reason="capability_not_registered_in_runtime",
                )
                return {
                    "status": rejected["status"],
                    "task_id": item["task_id"],
                    "execution_performed": False,
                    "wake_schedule": self._schedule_next(self.MIN_NEXT_TASK_DELAY_SECONDS),
                }
            expected = (
                capability.get("risk") == item["risk"]
                and capability.get("estimated_runtime_seconds") == item["estimated_runtime_seconds"]
                and capability.get("estimated_ram_mb") == item["estimated_ram_mb"]
                and capability.get("checkpointable") is True
            )
            if not expected:
                rejected = self.queue.fail(
                    item["task_id"], self.worker_id,
                    reason="queued_descriptor_does_not_match_registered_capability",
                )
                return {
                    "status": rejected["status"],
                    "task_id": item["task_id"],
                    "execution_performed": False,
                    "wake_schedule": self._schedule_next(self.MIN_NEXT_TASK_DELAY_SECONDS),
                }

        status_reader = getattr(self.orchestrator, "task_execution_status", None)
        if callable(status_reader) and status_reader(item["task_id"]) == "completed":
            self.queue.complete(
                item["task_id"], self.worker_id,
                summary="reconciled_after_worker_restart",
            )
            return {
                "status": "completed_reconciled",
                "task_id": item["task_id"],
                "completion_receipt_valid": True,
                "execution_performed": False,
                "wake_schedule": self._schedule_next(self.MIN_NEXT_TASK_DELAY_SECONDS),
            }

        task = {
            "id": item["task_id"],
            "name": item["name"],
            "capability": item["capability"],
            "args": item["args"],
            "kwargs": item["kwargs"],
        }
        try:
            result = self.orchestrator.run_parallel(
                [task],
                runtime_context=runtime_context,
                resource_snapshot=resource_snapshot,
                work_mode=work_mode,
            )
        except PermissionError as exc:
            self.queue.release(
                item["task_id"], self.worker_id,
                reason=str(exc)[:240] or "governor_deferred",
                count_attempt=False,
            )
            return {
                "status": "deferred",
                "task_id": item["task_id"],
                "reason": str(exc)[:240],
                "execution_performed": False,
                "wake_schedule": self._schedule_next(900),
            }
        except Exception as exc:
            retry = self.queue.retry(
                item["task_id"], self.worker_id,
                reason=f"{type(exc).__name__}: {exc}"[:240],
            )
            return {
                "status": retry["status"],
                "task_id": item["task_id"],
                "reason": str(exc)[:240],
                "execution_performed": False,
                "wake_schedule": self._schedule_next(60),
            }

        task_outcomes = result.get("tasks") if isinstance(result, dict) else None
        outcome = task_outcomes[0] if isinstance(task_outcomes, list) and task_outcomes else {}
        resource_receipt = result.get("resource_session") if isinstance(result, dict) else None
        checkpoint_sequence = (
            resource_receipt.get("checkpoint_sequence")
            if isinstance(resource_receipt, dict) else None
        )
        receipt_valid = (
            isinstance(result, dict)
            and result.get("status") == "completed"
            and result.get("execution_performed") is True
            and type(result.get("total")) is int
            and result.get("total") == 1
            and type(result.get("completed")) is int
            and result.get("completed") == 1
            and type(result.get("failed")) is int
            and result.get("failed") == 0
            and isinstance(task_outcomes, list)
            and len(task_outcomes) == 1
            and isinstance(outcome, dict)
            and outcome.get("id") == item["task_id"]
            and outcome.get("status") == "completed"
            and outcome.get("error") is None
            and isinstance(resource_receipt, dict)
            and resource_receipt.get("mode") == work_mode
            and resource_receipt.get("status") == "bounded"
            and resource_receipt.get("checkpoint_required") is True
            and isinstance(checkpoint_sequence, int)
            and not isinstance(checkpoint_sequence, bool)
            and checkpoint_sequence > 0
        )
        if receipt_valid:
            self.queue.complete(item["task_id"], self.worker_id)
            status = "completed"
            delay = self.MIN_NEXT_TASK_DELAY_SECONDS
            failure_reason = None
        else:
            failure_reason = (
                "invalid_execution_completion_receipt"
                if isinstance(result, dict) and result.get("status") == "completed"
                else str(outcome.get("error", "task_failed"))[:240]
            )
            retry = self.queue.retry(
                item["task_id"], self.worker_id,
                reason=failure_reason,
            )
            status = retry["status"]
            delay = 60
        return {
            "status": status,
            "task_id": item["task_id"],
            "work_mode": work_mode,
            "orchestrator_result": result,
            "completion_receipt_valid": receipt_valid,
            "execution_performed": (
                result.get("execution_performed") is True
                if isinstance(result, dict) else False
            ),
            "reason": failure_reason,
            "wake_schedule": self._schedule_next(delay),
        }
