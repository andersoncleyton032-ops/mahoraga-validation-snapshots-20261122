"""Parallel research coordinator belonging to Mahoraga."""

from __future__ import annotations

from threading import Lock
from time import perf_counter, time_ns
from typing import Any
import hashlib
import inspect
import json
import math
import re
import time


class ExecutionDeadlineExceeded(TimeoutError):
    """A cooperative capability deadline was reached."""


class ExecutionCheckpointError(RuntimeError):
    """A background task failed to persist a valid recovery checkpoint."""


class ExecutionContext:
    """Cooperative budget plus bounded, durable task checkpoint support."""

    MAX_CHECKPOINT_BYTES = 16_384

    def __init__(
        self,
        max_runtime_seconds: float,
        max_memory_mb: float,
        *,
        resume_state: dict | None = None,
        checkpoint_callback=None,
        require_checkpoint: bool = False,
    ):
        self.started_at = time.monotonic()
        self.deadline = self.started_at + max_runtime_seconds
        self.max_runtime_seconds = float(max_runtime_seconds)
        self.max_memory_mb = float(max_memory_mb)
        self.resume_state = resume_state
        self._checkpoint_callback = checkpoint_callback
        self.require_checkpoint = require_checkpoint
        self.checkpoint_count = 0

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise ExecutionDeadlineExceeded(
                "O prazo cooperativo desta capacidade foi excedido."
            )

    def checkpoint(self, state: dict) -> dict:
        """Persist a small JSON checkpoint for safe resumption by task ID."""
        self.check()
        if not isinstance(state, dict):
            raise ExecutionCheckpointError("Checkpoint precisa ser um objeto JSON.")
        try:
            encoded = json.dumps(
                state, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ExecutionCheckpointError("Checkpoint não é JSON válido.") from exc
        if len(encoded) > self.MAX_CHECKPOINT_BYTES:
            raise ExecutionCheckpointError("Checkpoint excede 16384 bytes.")
        if not callable(self._checkpoint_callback):
            raise ExecutionCheckpointError("Persistência de checkpoint indisponível.")
        result = self._checkpoint_callback(state)
        self.check()
        self.checkpoint_count += 1
        return result


class ResearchOrchestrator:
    VERSION = "0.4.0"
    CHECKPOINT_EVENT = "orchestrator.task.checkpoint"
    MAX_CHECKPOINT_HISTORY = 1000
    MAX_WORKERS = 1
    MAX_TASKS_PER_BATCH = 1
    MAX_CAPABILITY_SECONDS = 20.0
    MAX_CAPABILITY_MEMORY_MB = 256.0
    DEFAULT_READ_ONLY_SECONDS = 1.0
    DEFAULT_READ_ONLY_MEMORY_MB = 16.0
    DEFAULT_LOCAL_COMPUTE_SECONDS = 2.0
    DEFAULT_LOCAL_COMPUTE_MEMORY_MB = 32.0

    ALLOWED_RISKS = {
        "read_only",
        "local_compute",
    }

    def __init__(
        self,
        cognitive,
        capability_manifest=None,
        autonomy=None,
        runtime_context_provider=None,
    ):
        self.cognitive = cognitive
        self.store = cognitive.store
        self.dharma = cognitive.dharma
        self.capability_manifest = capability_manifest
        self.autonomy = autonomy
        self.runtime_context_provider = runtime_context_provider
        self._run_lock = Lock()
        self._registry_lock = Lock()
        self._plan_lock = Lock()
        self._capabilities = {}

    def sync_manifest_catalog(self):
        """Sincroniza metadados declarativos sem ativar funções."""
        if self.capability_manifest is None:
            raise RuntimeError("Manifesto de capacidades não configurado.")

        return self.capability_manifest.sync_to_catalog(self.store)

    def _authorize(self):
        decision = self.dharma.evaluate("introspect")

        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _authorize_capability(self, task: dict) -> dict:
        action_by_risk = {
            "read_only": "read_only_capability",
            "local_compute": "local_compute",
        }
        action = action_by_risk[task["risk"]]
        decision = self.dharma.evaluate(
            action,
            context={
                "capability_id": task["capability"],
            },
        )
        if not decision.allowed:
            raise PermissionError(
                f"Capacidade {task['capability']} não autorizada: "
                f"{decision.reason}"
            )
        return {
            "risk_score": decision.risk_score,
            "category": decision.category,
            "reason": decision.reason,
            "discovery_allowed": decision.discovery_allowed,
            "experiment_allowed": decision.experiment_allowed,
            "promotion_allowed": decision.promotion_allowed,
        }

    def register_capability(
        self,
        capability_id: str,
        function,
        *,
        risk: str,
        description: str,
        estimated_runtime_seconds: float | None = None,
        estimated_ram_mb: float | None = None,
        checkpointable: bool = False,
        writes_internal_state: bool = False,
        external_effects_allowed: bool = False,
        network_access_allowed: bool = False,
        tool_dispatch_allowed: bool = False,
    ) -> dict:
        """Register a trusted internal function for controlled research use.

        Registration is a trust decision, not a sandbox. Functions that are
        not trusted must be isolated before being registered.
        """
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("Identificador de capacidade inválido.")

        capability_id = capability_id.strip()
        if len(capability_id) > 160 or not all(
            char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in capability_id
        ):
            raise ValueError("Identificador contém caracteres inválidos ou excede 160 caracteres.")

        if not callable(function):
            raise ValueError("A capacidade precisa fornecer uma função.")
        if not isinstance(checkpointable, bool):
            raise ValueError("checkpointable precisa ser booleano.")
        if not isinstance(writes_internal_state, bool):
            raise ValueError("writes_internal_state precisa ser booleano.")
        for flag, value in (
            ("external_effects_allowed", external_effects_allowed),
            ("network_access_allowed", network_access_allowed),
            ("tool_dispatch_allowed", tool_dispatch_allowed),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{flag} precisa ser booleano.")
        if writes_internal_state and (risk != "local_compute" or checkpointable is not True):
            raise PermissionError(
                "Gravações internas exigem local_compute e capacidade checkpointable."
            )

        if inspect.iscoroutinefunction(function):
            raise ValueError("Funções assíncronas não são aceitas nesta versão.")

        if not isinstance(risk, str) or risk not in self.ALLOWED_RISKS:
            raise PermissionError(f"Categoria de risco não permitida: {risk}")

        if not isinstance(description, str) or not description.strip():
            raise ValueError("A capacidade precisa de uma descrição.")

        default_seconds = (
            self.DEFAULT_READ_ONLY_SECONDS
            if risk == "read_only"
            else self.DEFAULT_LOCAL_COMPUTE_SECONDS
        )
        default_ram = (
            self.DEFAULT_READ_ONLY_MEMORY_MB
            if risk == "read_only"
            else self.DEFAULT_LOCAL_COMPUTE_MEMORY_MB
        )
        estimated_runtime_seconds = (
            default_seconds
            if estimated_runtime_seconds is None
            else estimated_runtime_seconds
        )
        estimated_ram_mb = (
            default_ram if estimated_ram_mb is None else estimated_ram_mb
        )
        for value, name, maximum in (
            (estimated_runtime_seconds, "estimated_runtime_seconds", self.MAX_CAPABILITY_SECONDS),
            (estimated_ram_mb, "estimated_ram_mb", self.MAX_CAPABILITY_MEMORY_MB),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
                or float(value) > maximum
            ):
                raise ValueError(f"{name} fora do limite permitido.")

        with self._registry_lock:
            if capability_id in self._capabilities:
                raise ValueError(f"Capacidade já registrada: {capability_id}")

            existing = next(
                (
                    item
                    for item in self.store.list_capabilities()
                    if item["capability_id"] == capability_id
                ),
                None,
            )

            if self.capability_manifest is not None:
                declared = self.capability_manifest.get(capability_id)

                if declared is None:
                    raise PermissionError(
                        f"Capacidade não declarada no manifesto: {capability_id}"
                    )

                if not declared["enabled"]:
                    raise PermissionError(
                        f"Capacidade desabilitada no manifesto: {capability_id}"
                    )

                if declared["risk"] != risk:
                    raise PermissionError(
                        f"Risco incompatível com o manifesto: {capability_id}"
                    )
                declared_metadata = declared.get("metadata", {})
                declared_internal_write = (
                    declared_metadata.get("writes_internal_state", False)
                    if isinstance(declared_metadata, dict) else False
                )
                if declared_internal_write is not writes_internal_state:
                    raise PermissionError(
                        f"Escopo de gravação interna incompatível com o manifesto: {capability_id}"
                    )
                for flag, value in (
                    ("external_effects_allowed", external_effects_allowed),
                    ("network_access_allowed", network_access_allowed),
                    ("tool_dispatch_allowed", tool_dispatch_allowed),
                ):
                    if declared_metadata.get(flag, False) is not value:
                        raise PermissionError(
                            f"Contrato de efeitos incompatível com o manifesto: {capability_id}"
                        )

                if existing is None:
                    raise PermissionError(
                        "Capacidade ainda não sincronizada com o catálogo; "
                        "execute sync_manifest_catalog() explicitamente."
                    )

            if existing is not None:
                if not existing["enabled"]:
                    raise PermissionError(
                        f"Capacidade desabilitada no catálogo: {capability_id}"
                    )
                if existing["risk"] != risk:
                    raise PermissionError(
                        f"Risco incompatível com o catálogo: {capability_id}"
                    )
                existing_metadata = existing.get("metadata", {})
                existing_internal_write = (
                    existing_metadata.get("writes_internal_state", False)
                    if isinstance(existing_metadata, dict) else False
                )
                if existing_internal_write is not writes_internal_state:
                    raise PermissionError(
                        f"Escopo de gravação interna incompatível com o catálogo: {capability_id}"
                    )
                for flag, value in (
                    ("external_effects_allowed", external_effects_allowed),
                    ("network_access_allowed", network_access_allowed),
                    ("tool_dispatch_allowed", tool_dispatch_allowed),
                ):
                    if existing_metadata.get(flag, False) is not value:
                        raise PermissionError(
                            f"Contrato de efeitos incompatível com o catálogo: {capability_id}"
                        )
            else:
                definition = {
                    "name": capability_id,
                    "purpose": description.strip(),
                    "description": description.strip(),
                    "version": "0.1.0",
                    "risk": risk,
                    "maturity_state": "implemented",
                    "source_module": getattr(function, "__module__", ""),
                    "operations": [
                        getattr(function, "__name__", type(function).__name__)
                    ],
                    "inputs": {},
                    "outputs": {},
                    "dependencies": [],
                    "tools": [],
                    "limitations": [
                        "Vínculo executável mantido somente no registro em memória.",
                        "Registro não comprova testes ou validação em condições reais.",
                    ],
                    "resource_requirements": {},
                    "validation": {
                        "registration_verified": True,
                        "individual_tests_passed": False,
                        "integration_tests_passed": False,
                        "real_world_validated": False,
                    },
                    "enabled": True,
                    "metadata": {
                        "binding_type": "explicit_trusted_runtime_registration",
                        "callable_name": getattr(function, "__name__", None),
                        "checkpointable": checkpointable,
                        "writes_internal_state": writes_internal_state,
                        "external_effects_allowed": external_effects_allowed,
                        "network_access_allowed": network_access_allowed,
                        "tool_dispatch_allowed": tool_dispatch_allowed,
                    },
                }
                self.store.upsert_capability(capability_id, definition)

            self._capabilities[capability_id] = {
                "function": function,
                "risk": risk,
                "description": description.strip(),
                "estimated_runtime_seconds": float(estimated_runtime_seconds),
                "estimated_ram_mb": float(estimated_ram_mb),
                "checkpointable": checkpointable,
                "writes_internal_state": writes_internal_state,
                "external_effects_allowed": external_effects_allowed,
                "network_access_allowed": network_access_allowed,
                "tool_dispatch_allowed": tool_dispatch_allowed,
            }

        return {
            "id": capability_id,
            "risk": risk,
            "description": description.strip(),
            "registered": True,
        }

    def capability_descriptor(self, capability_id: str) -> dict | None:
        """Expose only registered capability limits for queue descriptor validation."""
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("capability_id inválido.")
        with self._registry_lock:
            capability = self._capabilities.get(capability_id.strip())
            if capability is None:
                return None
            return {
                "id": capability_id.strip(),
                "risk": capability["risk"],
                "estimated_runtime_seconds": capability["estimated_runtime_seconds"],
                "estimated_ram_mb": capability["estimated_ram_mb"],
                "checkpointable": capability["checkpointable"],
                "writes_internal_state": capability["writes_internal_state"],
                "external_effects_allowed": capability["external_effects_allowed"],
                "network_access_allowed": capability["network_access_allowed"],
                "tool_dispatch_allowed": capability["tool_dispatch_allowed"],
            }

    def _validate_task(self, task: dict) -> dict:
        if not isinstance(task, dict):
            raise ValueError("Cada tarefa deve ser um dicionário.")

        if "function" in task:
            raise ValueError(
                "Tarefas não podem fornecer função; use um identificador de capacidade."
            )

        task_id = task.get("id")
        name = task.get("name")
        capability_id = task.get("capability")
        args = task.get("args", ())
        kwargs = task.get("kwargs", {})

        if not isinstance(kwargs, dict):
            raise ValueError("kwargs precisa ser um dicionário.")
        if "execution_context" in kwargs:
            raise ValueError("execution_context é fornecido exclusivamente pelo Orchestrator.")

        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or len(task_id) > 160
        ):
            raise ValueError("Toda tarefa precisa de um ID válido de até 160 caracteres.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Toda tarefa precisa de um nome.")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("Toda tarefa precisa de um identificador de capacidade.")
        if not isinstance(args, (tuple, list)):
            raise ValueError("args precisa ser uma lista ou tupla.")
        with self._registry_lock:
            capability = self._capabilities.get(capability_id.strip())
        if capability is None:
            raise ValueError(f"Capacidade não registrada: {capability_id}")

        function = capability["function"]
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "A capacidade precisa expor assinatura verificável e aceitar execution_context."
            ) from exc

        context_parameter = signature.parameters.get("execution_context")
        accepts_context = (
            context_parameter is not None
            and context_parameter.kind in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        ) or (
            context_parameter is None
            and any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        )
        if not accepts_context:
            raise ValueError(
                "A capacidade precisa aceitar execution_context por palavra-chave "
                "para verificar seu prazo."
            )

        return {
            "id": task_id.strip(),
            "name": name.strip(),
            "capability": capability_id.strip(),
            "function": function,
            "args": tuple(args),
            "kwargs": dict(kwargs),
            "risk": capability["risk"],
            "description": capability["description"],
            "estimated_runtime_seconds": capability["estimated_runtime_seconds"],
            "estimated_ram_mb": capability["estimated_ram_mb"],
            "checkpointable": capability["checkpointable"],
            "writes_internal_state": capability["writes_internal_state"],
            "external_effects_allowed": capability["external_effects_allowed"],
            "network_access_allowed": capability["network_access_allowed"],
            "tool_dispatch_allowed": capability["tool_dispatch_allowed"],
        }

    @staticmethod
    def _execute(task: dict, execution_context: ExecutionContext) -> dict:
        started = perf_counter()
        try:
            execution_context.check()
            result = task["function"](
                *task["args"],
                **task["kwargs"],
                execution_context=execution_context,
            )
            execution_context.check()
            if execution_context.require_checkpoint and execution_context.checkpoint_count < 1:
                raise ExecutionCheckpointError(
                    "Tarefa background terminou sem persistir checkpoint nesta execução."
                )
            return {
                "id": task["id"],
                "name": task["name"],
                "capability": task["capability"],
                "risk": task["risk"],
                "external_effects_allowed": task["external_effects_allowed"],
                "network_access_allowed": task["network_access_allowed"],
                "tool_dispatch_allowed": task["tool_dispatch_allowed"],
                "status": "completed",
                "duration_seconds": round(perf_counter() - started, 6),
                "result": result,
                "error": None,
                "deadline_enforcement": "cooperative",
            }
        except Exception as exc:
            return {
                "id": task["id"],
                "name": task["name"],
                "capability": task["capability"],
                "risk": task["risk"],
                "status": "failed",
                "duration_seconds": round(perf_counter() - started, 6),
                "result": None,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc)[:300],
                },
                "deadline_enforcement": "cooperative",
            }

    def _checkpoint_sequence_key(self, task_id: str) -> str:
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        return f"orchestrator.task.checkpoint:{digest}"

    def _load_task_checkpoint(self, task_id: str, capability_id: str) -> dict:
        total = self.store.count_events(self.CHECKPOINT_EVENT)
        events = self.store.list_events(
            limit=self.MAX_CHECKPOINT_HISTORY,
            event_type=self.CHECKPOINT_EVENT,
        )
        if total > len(events):
            raise RuntimeError(
                "Histórico de checkpoints excede a janela verificável; retomada bloqueada."
            )
        for event in events:
            payload = event.get("payload")
            if not isinstance(payload, dict) or payload.get("task_id") != task_id:
                continue
            state = payload.get("state")
            sequence = payload.get("sequence")
            if (
                not isinstance(state, dict)
                or payload.get("task_capability") != capability_id
                or isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 1
            ):
                raise RuntimeError("Checkpoint persistido inválido ou incompatível; retomada bloqueada.")
            try:
                encoded = json.dumps(
                    state, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError, RecursionError) as exc:
                raise RuntimeError("Checkpoint persistido não é JSON válido.") from exc
            if len(encoded) > ExecutionContext.MAX_CHECKPOINT_BYTES:
                raise RuntimeError("Checkpoint persistido excede o limite; retomada bloqueada.")
            return {"sequence": sequence, "state": state, "event_id": event.get("id")}
        return {"sequence": 0, "state": None, "event_id": None}

    @staticmethod
    def _task_completion_event_type(task_id: str) -> str:
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        return f"orchestrator.task.completed.{digest}"

    def _mark_task_completed(self, task_id: str) -> None:
        event_type = self._task_completion_event_type(task_id)
        self.store.record_event_once(
            event_type,
            "completed",
            {"task_id": task_id, "status": "completed"},
        )

    def _task_already_completed(self, task_id: str) -> bool:
        event_type = self._task_completion_event_type(task_id)
        events = self.store.list_events(limit=1, event_type=event_type)
        if not events:
            return False
        payload = events[0].get("payload")
        if (
            not isinstance(payload, dict)
            or payload.get("task_id") != task_id
            or payload.get("status") != "completed"
        ):
            raise RuntimeError("Registro de conclusão incompatível; reexecução bloqueada.")
        return True

    def task_execution_status(self, task_id: str) -> str:
        """Return a conservative durable status for scheduler crash reconciliation."""
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 160:
            raise ValueError("task_id inválido.")
        return "completed" if self._task_already_completed(task_id.strip()) else "not_completed"

    def _record(self, event_type: str, payload: dict,
                severity: str = "info") -> None:
        self.store.record_event(
            event_type=event_type,
            payload=payload,
            severity=severity,
        )

    @staticmethod
    def _bounded_number(value, *, name: str, maximum: float) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise PermissionError(f"Autorização inválida: {name} não é numérico.")
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise PermissionError(f"Autorização inválida: {name}.") from exc
        if not math.isfinite(number) or number <= 0 or number > maximum:
            raise PermissionError(f"Autorização inválida: {name} fora do limite.")
        return number

    def _validate_governor_session(self, session: dict) -> dict:
        if not isinstance(session, dict) or session.get("status") != "bounded":
            raise PermissionError("AutonomyGovernor não concedeu uma janela de execução.")
        budget = session.get("budget")
        if not isinstance(budget, dict):
            raise PermissionError("AutonomyGovernor retornou orçamento inválido.")
        max_seconds = self._bounded_number(
            budget.get("max_task_seconds"),
            name="budget.max_task_seconds",
            maximum=self.MAX_CAPABILITY_SECONDS,
        )
        max_memory = self._bounded_number(
            budget.get("max_task_ram_mb"),
            name="budget.max_task_ram_mb",
            maximum=self.MAX_CAPABILITY_MEMORY_MB,
        )
        concurrent_limit = budget.get("max_concurrent_tasks")
        if (
            isinstance(concurrent_limit, bool)
            or not isinstance(concurrent_limit, int)
            or concurrent_limit != 1
        ):
            raise PermissionError("Orçamento não autoriza exatamente uma tarefa.")
        for flag in (
            "continuous_loop_allowed",
            "network_allowed",
            "camera_capture_allowed",
            "microphone_capture_allowed",
            "android_changes_allowed",
            "package_installation_allowed",
            "project_writes_allowed",
            "workspace_writes_allowed",
        ):
            if budget.get(flag) is not False:
                raise PermissionError(
                    f"Orçamento inválido: {flag} precisa permanecer desativado."
                )
        return {
            "max_task_seconds": max_seconds,
            "max_task_ram_mb": max_memory,
        }

    def _validate_governor_permit(
        self, permit: dict, task: dict, budget: dict,
        work_mode: str = "foreground",
    ) -> tuple[float, float]:
        if not isinstance(permit, dict):
            raise PermissionError("AutonomyGovernor retornou autorização inválida.")
        if permit.get("task_id") != task["id"]:
            raise PermissionError("Autorização vinculada a outra tarefa.")
        if permit.get("risk") != task["risk"]:
            raise PermissionError("Autorização não corresponde ao risco registrado.")
        if permit.get("continuous_loop") is not False:
            raise PermissionError("Autorização não permite execução contínua.")
        expected_internal_write = task.get("writes_internal_state") is True
        expected_side_effects = (
            "bounded_internal_state" if expected_internal_write else "none"
        )
        if permit.get("writes_internal_state", False) is not expected_internal_write:
            raise PermissionError("Autorização não corresponde ao escopo de gravação interna.")
        if permit.get("side_effects") != expected_side_effects:
            raise PermissionError("Autorização permite efeitos colaterais não previstos.")
        if permit.get("execution_performed") is not False:
            raise PermissionError("Governor não pode declarar execução antecipadamente.")
        checkpoint_required = (
            expected_internal_write
            or work_mode in {"background_idle", "background_companion"}
        )
        if checkpoint_required:
            if permit.get("checkpoint_required") is not True:
                raise PermissionError("Trabalho exige checkpoint obrigatório.")
            if permit.get("checkpointable_claimed") is not True:
                raise PermissionError("Permit não confirma capacidade checkpointable.")
            if permit.get("checkpointability_verified") is not False:
                raise PermissionError("Governor não pode declarar checkpointabilidade verificada.")
        if work_mode in {"background_idle", "background_companion"}:
            if permit.get("execution_mode") != work_mode:
                raise PermissionError("Permit não está vinculado ao modo background solicitado.")

        max_seconds = self._bounded_number(
            permit.get("max_runtime_seconds"),
            name="permit.max_runtime_seconds",
            maximum=min(
                self.MAX_CAPABILITY_SECONDS,
                task["estimated_runtime_seconds"],
                budget["max_task_seconds"],
            ),
        )
        max_memory = self._bounded_number(
            permit.get("max_memory_mb"),
            name="permit.max_memory_mb",
            maximum=min(
                self.MAX_CAPABILITY_MEMORY_MB,
                task["estimated_ram_mb"],
                budget["max_task_ram_mb"],
            ),
        )
        return max_seconds, max_memory

    def run_parallel(
        self,
        tasks: list[dict],
        max_workers: int = 1,
        *,
        runtime_context: dict | None = None,
        resource_snapshot: dict | None = None,
        work_mode: str = "foreground",
    ) -> dict[str, Any]:
        """Run one Governor-admitted task in foreground, companion or idle mode.

        Background modes are one-shot and require a declared checkpointable
        capability. Durable checkpoints seed a later invocation after process
        interruption; this method does not create an Android scheduler or
        promise wakeups. Deadlines are cooperative and RAM is admission-only.
        """
        if self.autonomy is None:
            raise RuntimeError("AutonomyGovernor obrigatório; execução bloqueada.")
        if not isinstance(work_mode, str) or work_mode not in {
            "foreground", "background_idle", "background_companion"
        }:
            raise ValueError("work_mode inválido.")

        self._authorize()
        if not isinstance(tasks, list):
            raise ValueError("tasks precisa ser uma lista.")
        if len(tasks) > self.MAX_TASKS_PER_BATCH:
            raise ValueError("Execução paralela desabilitada: uma tarefa por autorização.")
        if isinstance(max_workers, bool) or not isinstance(max_workers, int):
            raise ValueError("max_workers precisa ser um número inteiro.")
        if max_workers != 1:
            raise ValueError("O Governor atual permite somente uma tarefa por vez.")

        batch_id = f"research-{time_ns()}"
        if not tasks:
            return {
                "batch_id": batch_id,
                "status": "empty",
                "total": 0,
                "completed": 0,
                "failed": 0,
                "tasks": [],
                "execution_performed": False,
            }

        validated = [self._validate_task(task) for task in tasks]
        if len({task["id"] for task in validated}) != len(validated):
            raise ValueError("IDs de tarefas duplicados.")

        task = validated[0]
        task["authorization"] = self._authorize_capability(task)

        if runtime_context is None and callable(self.runtime_context_provider):
            runtime_context = self.runtime_context_provider()
        if not isinstance(runtime_context, dict):
            raise PermissionError(
                "Contexto Android ausente; execução permanece bloqueada."
            )
        if work_mode == "foreground":
            if (
                runtime_context.get("app_foreground") is not True
                or runtime_context.get("screen_interactive") is not True
            ):
                raise PermissionError(
                    "O modo foreground exige o Mahoraga em primeiro plano e tela interativa."
                )
        elif work_mode == "background_idle":
            if (
                runtime_context.get("app_foreground") is not False
                or runtime_context.get("screen_interactive") is not False
            ):
                raise PermissionError(
                    "O modo background_idle exige app em segundo plano e tela apagada."
                )
        elif (
            runtime_context.get("app_foreground") is not False
            or runtime_context.get("screen_interactive") is not True
        ):
            raise PermissionError(
                "O modo background_companion exige Mahoraga em segundo plano e tela interativa."
            )

        session = self.autonomy.evaluate_session(
            runtime_context,
            resource_snapshot=resource_snapshot,
            work_mode=work_mode,
        )
        budget = self._validate_governor_session(session)

        work_request = {
            "task_id": task["id"],
            "risk": task["risk"],
            "estimated_seconds": task["estimated_runtime_seconds"],
            "estimated_ram_mb": task["estimated_ram_mb"],
            "requires_network": False,
            "requires_camera": False,
            "requires_microphone": False,
            "writes_project": False,
            "installs_packages": False,
            "changes_android": False,
            "captures_sensitive_data": False,
            "persistent_external_change": False,
            "requires_audio_output": False,
            "internal_only": (
                task["writes_internal_state"]
                or work_mode in {"background_idle", "background_companion"}
            ),
            "checkpointable": task["checkpointable"],
            "writes_workspace": False,
            "writes_internal_state": task["writes_internal_state"],
        }
        admission = self.autonomy.evaluate_work(session, work_request)
        if not isinstance(admission, dict) or admission.get("allowed") is not True:
            reason = (
                admission.get("reason", "admission_denied")
                if isinstance(admission, dict)
                else "invalid_governor_response"
            )
            raise PermissionError(f"AutonomyGovernor bloqueou a tarefa: {reason}")

        permit = admission.get("permit")
        permitted_seconds, permitted_memory = self._validate_governor_permit(
            permit, task, budget, work_mode=work_mode
        )

        checkpoint_required = (
            task["writes_internal_state"]
            or work_mode in {"background_idle", "background_companion"}
        )
        checkpoint = (
            self._load_task_checkpoint(task["id"], task["capability"])
            if checkpoint_required
            else {"sequence": 0, "state": None, "event_id": None}
        )
        if checkpoint_required and self._task_already_completed(task["id"]):
            raise RuntimeError("Tarefa já concluída; reutilização do ID bloqueada.")

        checkpoint_sequence = [checkpoint["sequence"]]

        def persist_checkpoint(state: dict) -> dict:
            committed = self.store.record_versioned_event(
                self.CHECKPOINT_EVENT,
                self._checkpoint_sequence_key(task["id"]),
                checkpoint_sequence[0],
                {
                    "task_id": task["id"],
                    "state": state,
                    "task_capability": task["capability"],
                    "execution_mode": work_mode,
                },
                sequence_field="sequence",
            )
            checkpoint_sequence[0] = committed["sequence"]
            return committed

        execution_context = ExecutionContext(
            permitted_seconds,
            permitted_memory,
            resume_state=checkpoint["state"],
            checkpoint_callback=persist_checkpoint,
            require_checkpoint=checkpoint_required,
        )
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Já existe uma tarefa em execução.")

        try:
            self._record(
                "orchestrator.batch.started",
                {
                    "batch_id": batch_id,
                    "task_count": 1,
                    "max_workers": 1,
                    "governor_mode": session.get("mode"),
                    "permit": {
                        "max_runtime_seconds": permitted_seconds,
                        "max_memory_mb": permitted_memory,
                        "risk": permit["risk"],
                        "execution_mode": session.get("mode"),
                        "checkpoint_required": checkpoint_required,
                        "writes_internal_state": task["writes_internal_state"],
                    },
                },
            )
            outcome = self._execute(task, execution_context)
            if checkpoint_required and outcome["status"] == "completed":
                self._mark_task_completed(task["id"])
            completed = int(outcome["status"] == "completed")
            failed = 1 - completed
            status = "completed" if completed else "failed"
            self._record(
                "orchestrator.task.finished",
                {
                    "batch_id": batch_id,
                    "task_id": outcome["id"],
                    "name": outcome["name"],
                    "capability": outcome["capability"],
                    "risk": outcome["risk"],
                    "authorization": task["authorization"],
                    "status": outcome["status"],
                    "duration_seconds": outcome["duration_seconds"],
                    "error": outcome["error"],
                    "deadline_enforcement": outcome["deadline_enforcement"],
                },
                severity="info" if completed else "warning",
            )
            self._record(
                "orchestrator.batch.finished",
                {
                    "batch_id": batch_id,
                    "status": status,
                    "total": 1,
                    "completed": completed,
                    "failed": failed,
                },
                severity="info" if completed else "warning",
            )
            return {
                "batch_id": batch_id,
                "status": status,
                "total": 1,
                "completed": completed,
                "failed": failed,
                "tasks": [outcome],
                "resource_session": {
                    "mode": session.get("mode"),
                    "status": session.get("status"),
                    "budget": session.get("budget"),
                    "checkpoint_required": checkpoint_required,
                    "checkpoint_sequence": checkpoint_sequence[0],
                    "writes_internal_state": task["writes_internal_state"],
                },
                "execution_performed": True,
                "deadline_enforcement": "cooperative",
                "memory_enforcement": "admission_only",
            }
        finally:
            self._run_lock.release()

    def prepare_initiative_plan(
        self, candidate_id: str, *, approved: bool = False
    ) -> dict[str, Any]:
        """Persist a bounded research plan for a freshly reviewed initiative.

        This prepares a plan only. It never dispatches capabilities, accesses
        the network, changes Android state, or consolidates learning.
        """
        self._authorize()
        if approved is not True:
            raise PermissionError(
                "Persistir um plano de pesquisa exige aprovação explícita."
            )
        if (
            not isinstance(candidate_id, str)
            or not candidate_id.strip()
            or len(candidate_id) > 64
        ):
            raise ValueError("candidate_id inválido.")

        candidate_id = candidate_id.strip()
        review = self.cognitive.review_initiatives()
        if not isinstance(review, dict) or not isinstance(
            review.get("candidates"), list
        ):
            raise TypeError("A revisão de iniciativas retornou estrutura inválida.")
        candidate = next(
            (
                item for item in review["candidates"]
                if isinstance(item, dict)
                and item.get("candidate_id") == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "Iniciativa não encontrada na revisão atual; nenhum plano foi salvo."
            )

        title = candidate.get("title")
        question = candidate.get("description")
        source = candidate.get("source")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (title, question, source)
        ):
            raise ValueError("A iniciativa não contém título, pergunta e origem válidos.")

        import hashlib

        plan_id = "research-" + hashlib.sha256(
            candidate_id.encode("utf-8")
        ).hexdigest()[:24]
        memory_key = f"research_plan:{plan_id}"

        with self._plan_lock:
            existing = self.store.get_memory(memory_key)
            if existing is not None:
                plan = existing.get("value") if isinstance(existing, dict) else None
                if (
                    not isinstance(plan, dict)
                    or plan.get("plan_id") != plan_id
                    or plan.get("candidate_id") != candidate_id
                ):
                    raise RuntimeError(
                        "Registro de plano existente inválido; operação bloqueada."
                    )
                return {
                    "status": "already_prepared",
                    "plan": plan,
                    "execution_performed": False,
                    "tool_dispatch_performed": False,
                }

            evidence = candidate.get("evidence")
            if not isinstance(evidence, dict):
                evidence = {}
            import json

            try:
                evidence_size = len(json.dumps(
                    evidence,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "A evidência da iniciativa não é JSON válida."
                ) from exc
            if evidence_size > 8192:
                raise ValueError(
                    "A evidência excede o limite de 8192 bytes para um plano."
                )
            plan = {
                "schema": "mahoraga.research_plan",
                "version": "1.0",
                "plan_id": plan_id,
                "candidate_id": candidate_id,
                "title": title.strip()[:200],
                "research_question": question.strip()[:1000],
                "initiative_kind": str(candidate.get("kind", "unspecified"))[:80],
                "source": source.strip()[:120],
                "evidence": evidence,
                "status": "prepared_pending_execution_review",
                "stages": [
                    {
                        "id": "frame_question",
                        "objective": "Delimitar a pergunta e registrar hipótese testável.",
                        "completed": False,
                    },
                    {
                        "id": "inspect_internal_evidence",
                        "objective": "Revisar conhecimento, observações e proveniência já disponíveis.",
                        "completed": False,
                    },
                    {
                        "id": "design_controlled_method",
                        "objective": "Definir método read-only ou computação local de baixo risco.",
                        "completed": False,
                    },
                    {
                        "id": "define_evaluation",
                        "objective": "Definir métricas, baseline, critérios de refutação e limites.",
                        "completed": False,
                    },
                    {
                        "id": "review_findings",
                        "objective": "Avaliar resultados, incertezas e necessidade de validação independente.",
                        "completed": False,
                    },
                ],
                "acceptance_criteria": [
                    "Fontes e dados possuem proveniência identificável.",
                    "Método e resultados são reproduzíveis dentro dos limites disponíveis.",
                    "Hipótese pode ser refutada; ausência de evidência não é tratada como confirmação.",
                    "Limitações, falhas e resultados negativos são preservados.",
                    "Nenhum conhecimento é promovido sem validação apropriada.",
                ],
                "governance": {
                    "approval_contract_satisfied": True,
                    "human_review_required_before_execution": True,
                    "network_access_enabled": False,
                    "tool_dispatch_performed": False,
                    "android_system_changes_enabled": False,
                    "learning_consolidation_performed": False,
                },
                "execution_authorized": False,
                "execution_performed": False,
            }
            created = self.store.save_memory_if_absent(
                memory_key,
                plan,
                metadata={
                    "kind": "research_plan",
                    "candidate_id": candidate_id,
                    "source": source.strip()[:120],
                    "version": "1.0",
                },
            )
            if not created:
                existing = self.store.get_memory(memory_key)
                existing_plan = (
                    existing.get("value")
                    if isinstance(existing, dict) else None
                )
                if (
                    not isinstance(existing_plan, dict)
                    or existing_plan.get("plan_id") != plan_id
                    or existing_plan.get("candidate_id") != candidate_id
                ):
                    raise RuntimeError(
                        "Persistência concorrente produziu registro inválido."
                    )
                return {
                    "status": "already_prepared",
                    "plan": existing_plan,
                    "execution_performed": False,
                    "tool_dispatch_performed": False,
                }

        return {
            "status": "prepared",
            "plan": plan,
            "execution_performed": False,
            "tool_dispatch_performed": False,
        }

    def record_plan_result(
        self,
        plan_id: str,
        *,
        method: str,
        result_status: str,
        summary: str,
        evidence_refs: list[str],
        attempt_id: str = "initial",
        approved: bool = False,
    ) -> dict[str, Any]:
        """Record an explicitly approved, caller-reported result for a stored plan.

        This operation records a report as an unverified episodic experience.
        It does not execute the research, verify external evidence, update plan
        stages, or consolidate semantic knowledge.
        """
        if approved is not True:
            raise PermissionError(
                "Registrar resultado de pesquisa exige aprovação explícita."
            )
        self._authorize()
        if not isinstance(plan_id, str) or not re.fullmatch(
            r"research-[0-9a-f]{24}", plan_id
        ):
            raise ValueError("plan_id inválido.")

        entry = self.store.get_memory(f"research_plan:{plan_id}")
        plan = entry.get("value") if isinstance(entry, dict) else None
        if (
            not isinstance(plan, dict)
            or plan.get("schema") != "mahoraga.research_plan"
            or plan.get("plan_id") != plan_id
            or not isinstance(plan.get("candidate_id"), str)
            or plan.get("status") != "prepared_pending_execution_review"
        ):
            raise ValueError(
                "Plano inexistente, inválido ou fora do estado que aceita relatos."
            )
        governance = plan.get("governance")
        if (
            not isinstance(governance, dict)
            or governance.get("tool_dispatch_performed") is not False
            or governance.get("network_access_enabled") is not False
            or governance.get("learning_consolidation_performed") is not False
        ):
            raise RuntimeError(
                "A governança do plano não corresponde ao contrato esperado."
            )

        result = self.cognitive.record_research_result(
            plan_id=plan_id,
            candidate_id=plan["candidate_id"],
            initiative_kind=str(plan.get("initiative_kind", "unspecified")),
            initiative_source=str(plan.get("source", "unspecified")),
            method=method,
            result_status=result_status,
            summary=summary,
            evidence_refs=evidence_refs,
            attempt_id=attempt_id,
            approved=True,
        )
        return {
            **result,
            "plan_id": plan_id,
            "report_provenance": "caller_supplied_not_independently_verified",
            "plan_state_changed": False,
            "research_executed_by_this_call": False,
            "tool_dispatch_performed": False,
            "semantic_consolidation_performed": False,
        }

    def list_plan_results(
        self, plan_id: str, *, limit: int = 100
    ) -> dict[str, Any]:
        """Return bounded, read-only reports linked to one stored research plan."""
        self._authorize()
        if not isinstance(plan_id, str) or not re.fullmatch(
            r"research-[0-9a-f]{24}", plan_id
        ):
            raise ValueError("plan_id inválido.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit deve ser um inteiro entre 1 e 100.")

        entry = self.store.get_memory(f"research_plan:{plan_id}")
        plan = entry.get("value") if isinstance(entry, dict) else None
        if (
            not isinstance(plan, dict)
            or plan.get("schema") != "mahoraga.research_plan"
            or plan.get("plan_id") != plan_id
        ):
            raise ValueError("Plano de pesquisa não encontrado.")

        events = self.store.list_events(
            limit=1000,
            event_type=self.cognitive.adaptive_learning.EVENT_TYPE,
        )
        reports = []
        for event in events:
            payload = event.get("payload", {})
            references = (
                payload.get("references")
                if isinstance(payload, dict) else None
            )
            if (
                not isinstance(references, dict)
                or references.get("research_plan_id") != plan_id
            ):
                continue
            reports.append({
                "event_id": event.get("id"),
                "created_at": event.get("created_at"),
                "attempt_id": references.get("attempt_id", "initial"),
                "result_status": references.get(
                    "result_status", payload.get("outcome")
                ),
                "method": payload.get("action"),
                "summary": references.get("summary"),
                "evidence_refs": references.get("evidence_refs", []),
                "provenance": references.get(
                    "reported_by", "unknown_provenance"
                ),
                "independently_verified": False,
                "learning_state": payload.get("learning_state", "unknown"),
            })
            if len(reports) >= limit:
                break

        status_counts = {}
        for report in reports:
            status = report.get("result_status")
            if isinstance(status, str):
                status_counts[status] = status_counts.get(status, 0) + 1
        mixed_outcomes = len(status_counts) > 1
        source_window_may_be_truncated = len(events) == 1000
        result_limit_reached = len(reports) >= limit
        review_scope_complete = not (
            source_window_may_be_truncated or result_limit_reached
        )

        return {
            "status": "found" if reports else "no_reports",
            "plan_id": plan_id,
            "result_count": len(reports),
            "results": reports,
            "result_status_counts": status_counts,
            "consistency_status": (
                "no_reports" if not reports
                else "mixed_attempt_outcomes" if mixed_outcomes
                else "history_window_limited" if not review_scope_complete
                else "consistent_status"
            ),
            "review_required": mixed_outcomes or not review_scope_complete,
            "review_scope_complete": review_scope_complete,
            "source_event_window": 1000,
            "source_window_may_be_truncated": source_window_may_be_truncated,
            "result_limit_reached": result_limit_reached,
            "memory_modified": False,
            "execution_performed": False,
            "semantic_consolidation_performed": False,
        }

    def draft_query_plan(
        self,
        question: str,
        *,
        evidence_gap: str,
        source_candidate_count: int = 0,
    ) -> dict[str, Any]:
        """Prepare a research plan only; never persist, access network or dispatch.

        Execution must use a separately registered capability and explicit approval.
        """
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 1000
            or "\x00" in question
        ):
            raise ValueError("A pergunta de pesquisa precisa ter até 1000 caracteres.")
        allowed_gaps = {
            "no_local_evidence",
            "insufficient_provenance",
            "contradictory_evidence",
            "unverified_sources",
        }
        if not isinstance(evidence_gap, str) or evidence_gap not in allowed_gaps:
            raise ValueError("evidence_gap não pertence ao contrato permitido.")
        if (
            isinstance(source_candidate_count, bool)
            or not isinstance(source_candidate_count, int)
            or not 0 <= source_candidate_count <= 1000
        ):
            raise ValueError("source_candidate_count precisa estar entre 0 e 1000.")

        normalized_question = question.strip()
        request_digest = hashlib.sha256(
            (evidence_gap + "\n" + normalized_question).encode("utf-8")
        ).hexdigest()[:24]
        orchestrator_status = self.status()
        runtime_bound_count = orchestrator_status.get("runtime_bound_count", 0)
        network_enabled = orchestrator_status.get("network_access_enabled") is True
        registered = orchestrator_status.get("registered_capabilities", [])
        registered_ids = [
            item.get("id")
            for item in registered
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        blockers = []
        if runtime_bound_count == 0:
            blockers.append("no_registered_research_capabilities")
        if not network_enabled:
            blockers.append("network_access_disabled")
        return {
            "schema": "mahoraga.research_request",
            "version": "1.0",
            "request_id": "research-request-" + request_digest,
            "question": normalized_question,
            "evidence_gap": evidence_gap,
            "source_candidate_count": source_candidate_count,
            "status": "draft_only",
            "stages": [
                {
                    "id": "frame_question",
                    "objective": "Delimitar escopo, período, entidades e critérios de resposta.",
                },
                {
                    "id": "acquire_sources",
                    "objective": "Localizar fontes primárias e secundárias adequadas à pergunta.",
                },
                {
                    "id": "verify_provenance",
                    "objective": "Registrar origem, data, integridade e contexto de cada fonte.",
                },
                {
                    "id": "cross_check",
                    "objective": "Comparar fontes independentes, divergências e incertezas.",
                },
                {
                    "id": "synthesize",
                    "objective": "Produzir síntese rastreável sem promover hipótese a fato.",
                },
            ],
            "capability_state": {
                "registered_capability_count": runtime_bound_count,
                "registered_capabilities": registered_ids,
                "network_access_enabled": network_enabled,
                "execution_available": bool(runtime_bound_count and network_enabled),
                "blockers": blockers,
            },
            "governance": {
                "execution_authorized": False,
                "user_approval_required_before_execution": True,
                "network_access_enabled": False,
                "tool_dispatch_performed": False,
                "memory_modified": False,
                "semantic_consolidation_performed": False,
            },
            "persistence_performed": False,
            "execution_performed": False,
        }

    def status(self) -> dict:
        with self._registry_lock:
            registered = {
                capability_id: capability
                for capability_id, capability in self._capabilities.items()
            }

        catalog = self.store.list_capabilities()
        runtime_bindings = set(registered)

        return {
            "component": "ResearchOrchestrator",
            "version": self.VERSION,
            "max_workers": self.MAX_WORKERS,
            "max_tasks_per_batch": self.MAX_TASKS_PER_BATCH,
            "allowed_risks": sorted(self.ALLOWED_RISKS),
            "autonomy_governor_connected": self.autonomy is not None,
            "runtime_context_provider_available": callable(self.runtime_context_provider),
            "parallel_execution_enabled": False,
            "deadline_enforcement": "cooperative",
            "memory_enforcement": "admission_only",
            "manifest": (
                self.capability_manifest.status()
                if self.capability_manifest is not None
                else {
                    "state": "not_configured",
                    "valid": False,
                    "declared_count": 0,
                    "executable_bindings": 0,
                    "code_loading_enabled": False,
                }
            ),
            "registered_capabilities": [
                {
                    "id": capability_id,
                    "risk": capability["risk"],
                    "description": capability["description"],
                }
                for capability_id, capability in sorted(registered.items())
            ],
            "persistent_capabilities": [
                {
                    "id": item["capability_id"],
                    "name": item["name"],
                    "risk": item["risk"],
                    "maturity_state": item["maturity_state"],
                    "enabled": item["enabled"],
                    "runtime_bound": item["capability_id"] in runtime_bindings,
                }
                for item in catalog
            ],
            "catalog_count": len(catalog),
            "runtime_bound_count": len(runtime_bindings),
            "unbound_catalog_count": sum(
                item["capability_id"] not in runtime_bindings
                for item in catalog
            ),
            "shared_store": self.store is self.cognitive.store,
            "network_access_enabled": False,
            "android_system_changes_enabled": False,
            "research_result_feedback_enabled": True,
            "research_result_provenance": "caller_supplied_not_independently_verified",
            "automatic_result_verification": False,
            "automatic_semantic_consolidation": False,
        }
