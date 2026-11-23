"""Governed execution of declarative procedural skills.

The v1 executor runs local foreground read-only skills one step at a time.
It delegates every step to ResearchOrchestrator and never loads code from a
skill package or invokes shell commands.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Any


class ProceduralSkillExecutionError(RuntimeError):
    """A procedural skill could not be safely executed."""


class ProceduralSkillExecutor:
    VERSION = "0.1.0"
    MAX_RUN_ID_LENGTH = 64

    def __init__(self, registry, adapters, orchestrator, store):
        if registry is None or adapters is None or orchestrator is None or store is None:
            raise ValueError("Registry, adapters, orchestrator e store são obrigatórios.")
        self.registry = registry
        self.adapters = adapters
        self.orchestrator = orchestrator
        self.store = store

    def status(self) -> dict:
        registry_status = self.registry.status()
        return {
            "component": "ProceduralSkillExecutor",
            "version": self.VERSION,
            "execution_path_implemented": True,
            "supported_work_mode": "foreground",
            "background_execution_supported": False,
            "network_allowed": False,
            "external_effects_allowed": False,
            "workspace_writes_allowed": False,
            "tool_dispatch_performed": False,
            "declared_skill_count": registry_status.get("declared_count", 0),
            "execution_requires_registry_readiness": True,
        }

    @staticmethod
    def _sha256_json(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _resolve_bindings(bindings: dict, inputs: dict, results: dict) -> dict:
        resolved = {}
        for target, source in bindings.items():
            if source.startswith("input."):
                key = source[6:]
                if key not in inputs:
                    raise ProceduralSkillExecutionError(
                        f"Entrada ausente para binding: {source}"
                    )
                resolved[target] = inputs[key]
            elif source.startswith("step.") and source.endswith(".result"):
                step_id = source[5:-7]
                if step_id not in results:
                    raise ProceduralSkillExecutionError(
                        f"Resultado de etapa ainda não disponível: {source}"
                    )
                resolved[target] = results[step_id]
            else:
                raise ProceduralSkillExecutionError(
                    f"Binding não suportado: {source}"
                )
        return resolved

    @staticmethod
    def _validate_output_schema(schema: dict, output: dict) -> None:
        for name, descriptor in schema.items():
            if descriptor["required"] and name not in output:
                raise ProceduralSkillExecutionError(
                    f"Saída obrigatória ausente: {name}"
                )
            if name not in output:
                continue
            value = output[name]
            kind = descriptor["type"]
            valid = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "object": isinstance(value, dict),
                "array": isinstance(value, list),
            }[kind]
            if not valid:
                raise ProceduralSkillExecutionError(
                    f"Tipo de saída inválido em {name}; esperado {kind}."
                )

    def _record(self, event_type: str, payload: dict, severity: str = "info") -> None:
        self.store.record_event(event_type, payload, severity=severity)

    def execute(
        self,
        skill_id: str,
        inputs: dict | None = None,
        *,
        runtime_context: dict | None = None,
        resource_snapshot: dict | None = None,
        run_id: str | None = None,
        work_mode: str = "foreground",
    ) -> dict:
        """Execute a ready skill sequentially, under one permit per step."""
        if work_mode != "foreground":
            raise ProceduralSkillExecutionError(
                "A execução procedural v1 aceita somente foreground; "
                "background exige agendamento checkpointado por etapa."
            )
        if not self.registry.valid:
            raise ProceduralSkillExecutionError(
                "ProceduralSkillRegistry ausente ou inválido."
            )
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError("skill_id inválido.")
        if run_id is None:
            run_id = uuid.uuid4().hex
        if (
            not isinstance(run_id, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", run_id)
        ):
            raise ValueError("run_id precisa ter 1–64 caracteres seguros.")

        skill = self.registry.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        if skill["risk"] != "read_only":
            raise ProceduralSkillExecutionError(
                "A execução v1 aceita somente habilidades read_only."
            )

        binding_report = self.adapters.register_enabled()
        if binding_report.get("status") not in {"registered", "no_enabled_capabilities"}:
            return {
                "status": "blocked",
                "skill_id": skill_id,
                "run_id": run_id,
                "reason": "capability_binding_failed",
                "binding": binding_report,
                "execution_performed": False,
            }

        plan = self.registry.plan(skill_id, inputs)
        if plan.get("status") != "planned":
            self._record("procedural_skill.blocked", {
                "skill_id": skill_id,
                "skill_version": skill["version"],
                "run_id": run_id,
                "blockers": plan.get("readiness", {}).get("blockers", []),
                "execution_performed": False,
            }, severity="warning")
            return {
                "status": "blocked",
                "skill_id": skill_id,
                "run_id": run_id,
                "readiness": plan.get("readiness"),
                "execution_performed": False,
            }

        supplied = {} if inputs is None else dict(inputs)
        budget = skill["resource_budget"]
        max_runtime = float(budget["max_runtime_seconds"])
        max_ram = float(budget["max_ram_mb"])
        started = time.monotonic()
        step_results: dict[str, Any] = {}
        completed_steps = []
        self._record("procedural_skill.started", {
            "skill_id": skill_id,
            "skill_version": skill["version"],
            "run_id": run_id,
            "step_count": len(plan["steps"]),
            "budget": budget,
            "execution_performed": False,
        })

        for step in plan["steps"]:
            elapsed = time.monotonic() - started
            remaining = max_runtime - elapsed
            if remaining <= 0:
                result = {
                    "status": "deferred",
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "completed_steps": completed_steps,
                    "partial_results": step_results,
                    "reason": "skill_runtime_budget_exhausted",
                    "execution_performed": bool(completed_steps),
                }
                self._record("procedural_skill.deferred", {
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "completed_steps": completed_steps,
                    "reason": result["reason"],
                    "execution_performed": result["execution_performed"],
                }, severity="warning")
                return result

            capability = self.registry.capability_manifest.get(step["capability_id"])
            if not isinstance(capability, dict) or capability.get("enabled") is not True:
                reason = f"capability_not_enabled:{step['capability_id']}"
                self._record("procedural_skill.failed", {
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "completed_steps": completed_steps,
                    "reason": reason,
                    "execution_performed": bool(completed_steps),
                }, severity="warning")
                return {
                    "status": "failed",
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "completed_steps": completed_steps,
                    "partial_results": step_results,
                    "reason": reason,
                    "execution_performed": bool(completed_steps),
                }

            resources = capability.get("resource_requirements", {})
            estimated_seconds = resources.get("estimated_runtime_seconds")
            estimated_ram = resources.get("estimated_ram_mb")
            if (
                isinstance(estimated_seconds, bool)
                or not isinstance(estimated_seconds, (int, float))
                or estimated_seconds <= 0
                or estimated_seconds > min(remaining, max_runtime)
                or isinstance(estimated_ram, bool)
                or not isinstance(estimated_ram, (int, float))
                or estimated_ram <= 0
                or estimated_ram > max_ram
            ):
                reason = f"step_exceeds_skill_budget:{step['id']}"
                self._record("procedural_skill.failed", {
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "step_id": step["id"],
                    "completed_steps": completed_steps,
                    "reason": reason,
                    "execution_performed": bool(completed_steps),
                }, severity="warning")
                return {
                    "status": "blocked",
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "completed_steps": completed_steps,
                    "partial_results": step_results,
                    "reason": reason,
                    "execution_performed": bool(completed_steps),
                }

            try:
                kwargs = self._resolve_bindings(
                    step["input_bindings"], supplied, step_results
                )
                task_id = "skill-step-" + hashlib.sha256(
                    f"{run_id}:{skill_id}:{step['id']}".encode("utf-8")
                ).hexdigest()[:40]
                orchestrator_result = self.orchestrator.run_parallel(
                    [{
                        "id": task_id,
                        "name": step["purpose"][:120],
                        "capability": step["capability_id"],
                        "args": [],
                        "kwargs": kwargs,
                    }],
                    runtime_context=runtime_context,
                    resource_snapshot=resource_snapshot,
                    work_mode="foreground",
                )
                outcomes = (
                    orchestrator_result.get("tasks")
                    if isinstance(orchestrator_result, dict) else None
                )
                outcome = outcomes[0] if isinstance(outcomes, list) and len(outcomes) == 1 else None
                valid_receipt = (
                    isinstance(orchestrator_result, dict)
                    and orchestrator_result.get("status") == "completed"
                    and orchestrator_result.get("execution_performed") is True
                    and type(orchestrator_result.get("total")) is int
                    and orchestrator_result.get("total") == 1
                    and type(orchestrator_result.get("completed")) is int
                    and orchestrator_result.get("completed") == 1
                    and type(orchestrator_result.get("failed")) is int
                    and orchestrator_result.get("failed") == 0
                    and isinstance(outcome, dict)
                    and outcome.get("id") == task_id
                    and outcome.get("status") == "completed"
                    and outcome.get("error") is None
                )
                if step["checkpoint_required"]:
                    session = (
                        orchestrator_result.get("resource_session")
                        if isinstance(orchestrator_result, dict) else None
                    )
                    sequence = (
                        session.get("checkpoint_sequence")
                        if isinstance(session, dict) else None
                    )
                    valid_receipt = (
                        valid_receipt
                        and isinstance(sequence, int)
                        and not isinstance(sequence, bool)
                        and sequence > 0
                    )
                if not valid_receipt:
                    error = (
                        outcome.get("error")
                        if isinstance(outcome, dict) else None
                    )
                    reason = (
                        str(error)[:240]
                        if error is not None else "invalid_step_completion_receipt"
                    )
                    raise ProceduralSkillExecutionError(reason)
                value = outcome.get("result")
                self.registry._validate_json_value(value)
                result_sha256 = self._sha256_json(value)
                step_results[step["id"]] = value
                completed_steps.append(step["id"])
                self._record("procedural_skill.step.completed", {
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "step_id": step["id"],
                    "capability_id": step["capability_id"],
                    "result_sha256": result_sha256,
                    "checkpoint_required": step["checkpoint_required"],
                    "execution_performed": True,
                })
            except Exception as exc:
                reason = f"{type(exc).__name__}: {str(exc)[:240]}"
                self._record("procedural_skill.failed", {
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "step_id": step["id"],
                    "completed_steps": completed_steps,
                    "reason": reason,
                    "execution_performed": bool(completed_steps),
                }, severity="warning")
                return {
                    "status": "failed",
                    "skill_id": skill_id,
                    "run_id": run_id,
                    "failed_step": step["id"],
                    "completed_steps": completed_steps,
                    "partial_results": step_results,
                    "reason": reason,
                    "execution_performed": bool(completed_steps),
                }

        report = {
            "skill_id": skill_id,
            "skill_version": skill["version"],
            "run_id": run_id,
            "completed_steps": completed_steps,
            "step_results": step_results,
            "artifacts": list(skill["expected_artifacts"]),
            "provenance": skill["provenance"],
            "duration_seconds": round(time.monotonic() - started, 6),
            "execution_performed": True,
        }
        output = {"report": report}
        self._validate_output_schema(skill["output_schema"], output)
        self._record("procedural_skill.completed", {
            "skill_id": skill_id,
            "skill_version": skill["version"],
            "run_id": run_id,
            "completed_steps": completed_steps,
            "result_sha256": self._sha256_json(report),
            "execution_performed": True,
        })
        return {
            "status": "completed",
            "skill_id": skill_id,
            "run_id": run_id,
            "output": output,
            "execution_performed": True,
            "tool_dispatch_performed": False,
            "external_effects": False,
        }
