"""Versioned procedural-skill contracts bound to Mahoraga's existing capabilities.

This registry validates and ranks declarative procedures. It never imports code,
loads callables, executes shell commands, or grants permissions. Execution remains
the responsibility of ResearchOrchestrator and its explicit trusted bindings.
"""
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


class ProceduralSkillError(ValueError):
    """Invalid or unsafe procedural-skill package."""


class ProceduralSkillRegistry:
    SCHEMA = "mahoraga.procedural_skills"
    VERSION = "1.0.0"
    MAX_FILE_BYTES = 262144
    MAX_SKILLS = 128
    MAX_STEPS = 32
    MAX_RUNTIME_SECONDS = 20.0
    MAX_RAM_MB = 256.0
    RISK_ORDER = {"read_only": 0, "local_compute": 1}
    MATURITY_STATES = {
        "discovered", "researched", "designed", "staged",
        "validated", "operational", "specialized", "retired",
    }
    EXECUTABLE_FIELDS = {
        "callable", "function", "entrypoint", "import_path", "module_path",
        "code", "source_code", "python_code", "bytecode", "exec", "eval",
        "shell_command", "executable", "command", "commands",
        "shell", "script", "argv", "args",
    }
    PERMISSIONS = {"read_local_state", "local_compute"}
    VALIDATORS = {
        "schema", "capability_binding", "resource_budget", "provenance",
    }
    ENVIRONMENT_FIELDS = {
        "runtime", "network", "android_changes", "workspace_writes",
        "project_writes", "package_installation", "external_effects",
    }
    TOP_FIELDS = {"schema", "version", "skills"}
    SKILL_FIELDS = {
        "id", "version", "domain", "description", "intent_triggers",
        "exclusions", "input_schema", "output_schema", "preconditions",
        "environment", "dependencies", "tools", "risk", "permissions",
        "resource_budget", "steps", "expected_artifacts", "validators",
        "failure_recovery", "provenance", "rollback", "evidence",
        "maturity_state", "enabled",
    }
    STEP_FIELDS = {
        "id", "capability_id", "purpose", "input_bindings",
        "checkpoint_required",
    }

    def __init__(
        self, path, capability_manifest, *, orchestrator=None, store=None,
        evidence_verifier=None,
    ):
        self.path = Path(path)
        self.capability_manifest = capability_manifest
        self.orchestrator = orchestrator
        self.store = store
        self.evidence_verifier = evidence_verifier
        self._definitions: dict[str, dict] = {}
        self._state = "missing"
        self._error = None
        self._load()

    @staticmethod
    def _unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProceduralSkillError(f"Chave JSON duplicada: {key}")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value):
        raise ProceduralSkillError(f"Constante JSON inválida: {value}")

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return (
            isinstance(value, str)
            and 0 < len(value) <= 160
            and value == value.strip()
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is not None
        )

    @classmethod
    def _validate_json_value(cls, value: Any, depth: int = 0) -> None:
        if depth > 10:
            raise ProceduralSkillError("Profundidade excessiva no pacote.")
        if value is None or isinstance(value, (str, bool, int)):
            if isinstance(value, str) and len(value) > 4096:
                raise ProceduralSkillError("Texto excede 4096 caracteres.")
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ProceduralSkillError("Número não finito.")
            return
        if isinstance(value, list):
            if len(value) > 256:
                raise ProceduralSkillError("Lista excede 256 itens.")
            for item in value:
                cls._validate_json_value(item, depth + 1)
            return
        if isinstance(value, dict):
            if len(value) > 256:
                raise ProceduralSkillError("Objeto excede 256 campos.")
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ProceduralSkillError("Chave JSON precisa ser textual.")
                normalized = key.strip().lower().replace("-", "_")
                if normalized in cls.EXECUTABLE_FIELDS:
                    raise ProceduralSkillError(f"Campo executável proibido: {key}")
                cls._validate_json_value(item, depth + 1)
            return
        raise ProceduralSkillError("Tipo de valor não permitido no pacote.")

    @staticmethod
    def _string_list(value: Any, field: str, *, minimum: int = 0) -> list[str]:
        if not isinstance(value, list) or len(value) > 64 or len(value) < minimum:
            raise ProceduralSkillError(f"{field} precisa ser uma lista válida.")
        result = []
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 240:
                raise ProceduralSkillError(f"Item inválido em {field}.")
            result.append(item.strip())
        if len(set(result)) != len(result):
            raise ProceduralSkillError(f"{field} contém itens duplicados.")
        return result

    @classmethod
    def _validate_io_schema(cls, value: Any, field: str) -> dict:
        if not isinstance(value, dict) or len(value) > 64:
            raise ProceduralSkillError(f"{field} precisa ser um objeto limitado.")
        allowed_types = {"string", "integer", "number", "boolean", "object", "array"}
        result = {}
        for name, descriptor in value.items():
            if not cls._valid_id(name) or not isinstance(descriptor, dict):
                raise ProceduralSkillError(f"Campo inválido em {field}: {name}")
            if set(descriptor) - {"type", "required", "description"}:
                raise ProceduralSkillError(f"Descritor desconhecido em {field}.{name}")
            kind = descriptor.get("type")
            required = descriptor.get("required", False)
            description = descriptor.get("description", "")
            if kind not in allowed_types or not isinstance(required, bool):
                raise ProceduralSkillError(f"Tipo/required inválido em {field}.{name}")
            if not isinstance(description, str) or len(description) > 240:
                raise ProceduralSkillError(f"Descrição inválida em {field}.{name}")
            result[name] = {
                "type": kind, "required": required, "description": description,
            }
        return result

    def _validate_skill(self, item: Any) -> dict:
        if not isinstance(item, dict):
            raise ProceduralSkillError("Cada habilidade precisa ser um objeto.")
        unknown = set(item) - self.SKILL_FIELDS
        missing = self.SKILL_FIELDS - set(item)
        if unknown or missing:
            raise ProceduralSkillError(
                f"Campos inválidos; ausentes={sorted(missing)}, desconhecidos={sorted(unknown)}"
            )
        skill_id = item["id"]
        if not self._valid_id(skill_id):
            raise ProceduralSkillError("ID de habilidade inválido.")
        for field in ("version", "domain", "description", "risk", "maturity_state", "rollback"):
            value = item[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 240:
                raise ProceduralSkillError(f"Campo textual inválido: {field}")
        if item["risk"] not in self.RISK_ORDER:
            raise ProceduralSkillError("Classe de risco não permitida.")
        if item["maturity_state"] not in self.MATURITY_STATES:
            raise ProceduralSkillError("Estado de maturidade desconhecido.")
        if not isinstance(item["enabled"], bool):
            raise ProceduralSkillError("enabled precisa ser booleano.")
        if item["maturity_state"] == "retired" and item["enabled"]:
            raise ProceduralSkillError("Habilidade aposentada não pode estar habilitada.")
        if item["enabled"] and item["maturity_state"] not in {"operational", "specialized"}:
            raise ProceduralSkillError("Habilidade habilitada precisa estar operacional ou especializada.")

        triggers = self._string_list(item["intent_triggers"], "intent_triggers", minimum=1)
        exclusions = self._string_list(item["exclusions"], "exclusions")
        preconditions = self._string_list(item["preconditions"], "preconditions")
        dependencies = self._string_list(item["dependencies"], "dependencies")
        tools = self._string_list(item["tools"], "tools")
        artifacts = self._string_list(item["expected_artifacts"], "expected_artifacts", minimum=1)
        validators = self._string_list(item["validators"], "validators", minimum=1)
        if any(value not in self.VALIDATORS for value in validators):
            raise ProceduralSkillError("Validador desconhecido.")
        permissions = self._string_list(item["permissions"], "permissions")
        if any(value not in self.PERMISSIONS for value in permissions):
            raise ProceduralSkillError("Permissão fora da allowlist local.")
        if item["risk"] == "read_only" and "local_compute" in permissions:
            raise ProceduralSkillError("Habilidade read_only não pode solicitar local_compute.")

        inputs = self._validate_io_schema(item["input_schema"], "input_schema")
        outputs = self._validate_io_schema(item["output_schema"], "output_schema")
        for field in ("environment", "resource_budget", "failure_recovery", "provenance"):
            if not isinstance(item[field], dict):
                raise ProceduralSkillError(f"{field} precisa ser um objeto.")
        budget = item["resource_budget"]
        if set(budget) != {"max_runtime_seconds", "max_ram_mb", "max_steps"}:
            raise ProceduralSkillError("resource_budget possui contrato inválido.")
        seconds = budget["max_runtime_seconds"]
        ram = budget["max_ram_mb"]
        steps_limit = budget["max_steps"]
        if (
            isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(float(seconds)) or not 0 < seconds <= self.MAX_RUNTIME_SECONDS
            or isinstance(ram, bool) or not isinstance(ram, (int, float))
            or not math.isfinite(float(ram)) or not 0 < ram <= self.MAX_RAM_MB
            or isinstance(steps_limit, bool) or not isinstance(steps_limit, int)
            or not 1 <= steps_limit <= self.MAX_STEPS
        ):
            raise ProceduralSkillError("Orçamento de recursos fora dos limites.")
        if not item["steps"] or not isinstance(item["steps"], list) or len(item["steps"]) > self.MAX_STEPS:
            raise ProceduralSkillError("steps precisa conter de 1 a 32 etapas.")
        if len(item["steps"]) > steps_limit:
            raise ProceduralSkillError("Quantidade de etapas excede resource_budget.max_steps.")

        if not isinstance(item["failure_recovery"], dict):
            raise ProceduralSkillError("failure_recovery inválido.")
        recovery = item["failure_recovery"]
        if set(recovery) != {"retry_policy", "max_retries", "checkpoint_policy", "on_failure"}:
            raise ProceduralSkillError("Contrato de recuperação inválido.")
        if recovery["retry_policy"] not in {"none", "bounded"}:
            raise ProceduralSkillError("retry_policy desconhecida.")
        retries = recovery["max_retries"]
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 3:
            raise ProceduralSkillError("max_retries precisa estar entre 0 e 3.")
        if not all(isinstance(recovery[k], str) and recovery[k].strip() for k in ("checkpoint_policy", "on_failure")):
            raise ProceduralSkillError("Política de checkpoint/falha inválida.")

        provenance = item["provenance"]
        if set(provenance) != {"source", "license", "version"} or not all(
            isinstance(provenance[k], str) and provenance[k].strip()
            for k in ("source", "license", "version")
        ):
            raise ProceduralSkillError("Proveniência/licença incompleta.")
        environment = item["environment"]
        if set(environment) - self.ENVIRONMENT_FIELDS:
            raise ProceduralSkillError("environment contém campos desconhecidos.")
        if environment.get("runtime") != "local_python":
            raise ProceduralSkillError("Runtime fora do escopo local desta versão.")
        for field in (
            "network", "android_changes", "workspace_writes",
            "project_writes", "package_installation", "external_effects",
        ):
            value = environment.get(field, False)
            if not isinstance(value, bool) or value is not False:
                raise ProceduralSkillError(
                    f"Ambiente declarativo não pode habilitar efeito externo: {field}"
                )
        if not isinstance(item["evidence"], list) or len(item["evidence"]) > 64:
            raise ProceduralSkillError("evidence precisa ser uma lista limitada.")
        evidence = self._string_list(item["evidence"], "evidence")
        if item["maturity_state"] in {"operational", "specialized"} and not evidence:
            raise ProceduralSkillError("Maturidade operacional exige evidência registrada.")

        if self.capability_manifest is None or not self.capability_manifest.valid:
            raise ProceduralSkillError("CapabilityManifest ausente ou inválido.")
        steps = []
        seen_step_ids = set()
        estimated_total_seconds = 0.0
        for step in item["steps"]:
            if not isinstance(step, dict) or set(step) != self.STEP_FIELDS:
                raise ProceduralSkillError("Etapa possui campos inválidos.")
            step_id = step["id"]
            capability_id = step["capability_id"]
            if not self._valid_id(step_id) or step_id in seen_step_ids:
                raise ProceduralSkillError("ID de etapa inválido ou duplicado.")
            if not self._valid_id(capability_id):
                raise ProceduralSkillError("capability_id inválido.")
            if not isinstance(step["purpose"], str) or not step["purpose"].strip():
                raise ProceduralSkillError("purpose da etapa é obrigatório.")
            if not isinstance(step["checkpoint_required"], bool):
                raise ProceduralSkillError("checkpoint_required precisa ser booleano.")
            bindings = step["input_bindings"]
            if not isinstance(bindings, dict) or len(bindings) > 32:
                raise ProceduralSkillError("input_bindings inválido.")
            for target, source in bindings.items():
                if not self._valid_id(target) or not isinstance(source, str):
                    raise ProceduralSkillError("Binding de entrada inválido.")
                if source.startswith("input."):
                    if source[6:] not in inputs:
                        raise ProceduralSkillError("Binding referencia input inexistente.")
                elif source.startswith("step.") and source.endswith(".result"):
                    previous_id = source[5:-7]
                    if previous_id not in seen_step_ids:
                        raise ProceduralSkillError("Binding referencia etapa futura ou inexistente.")
                else:
                    raise ProceduralSkillError("Binding precisa apontar para input.* ou step.*.result.")
            capability = self.capability_manifest.get(capability_id)
            if capability is None:
                raise ProceduralSkillError(f"Capacidade não declarada: {capability_id}")
            if self.RISK_ORDER[capability["risk"]] > self.RISK_ORDER[item["risk"]]:
                raise ProceduralSkillError("Etapa excede a classe de risco da habilidade.")
            capability_budget = capability.get("resource_requirements", {})
            capability_seconds = capability_budget.get("estimated_runtime_seconds")
            capability_ram = capability_budget.get("estimated_ram_mb")
            if (
                isinstance(capability_seconds, bool)
                or not isinstance(capability_seconds, (int, float))
                or not math.isfinite(float(capability_seconds))
                or capability_seconds <= 0
                or capability_seconds > seconds
                or isinstance(capability_ram, bool)
                or not isinstance(capability_ram, (int, float))
                or not math.isfinite(float(capability_ram))
                or capability_ram <= 0
                or capability_ram > ram
            ):
                raise ProceduralSkillError(
                    f"Orçamento da capacidade excede o orçamento da habilidade: {capability_id}"
                )
            estimated_total_seconds += float(capability_seconds)
            if estimated_total_seconds > seconds:
                raise ProceduralSkillError(
                    "Soma dos tempos estimados das etapas excede o orçamento da habilidade."
                )
            seen_step_ids.add(step_id)
            steps.append({
                "id": step_id,
                "capability_id": capability_id,
                "purpose": step["purpose"].strip(),
                "input_bindings": deepcopy(bindings),
                "checkpoint_required": step["checkpoint_required"],
            })

        result = deepcopy(item)
        result["intent_triggers"] = triggers
        result["exclusions"] = exclusions
        result["preconditions"] = preconditions
        result["dependencies"] = dependencies
        result["tools"] = tools
        result["expected_artifacts"] = artifacts
        result["validators"] = validators
        result["permissions"] = permissions
        result["input_schema"] = inputs
        result["output_schema"] = outputs
        result["evidence"] = evidence
        result["steps"] = steps
        result["resource_budget"] = {
            "max_runtime_seconds": float(seconds),
            "max_ram_mb": float(ram),
            "max_steps": steps_limit,
        }
        self._validate_json_value(result)
        return result

    def _load(self) -> None:
        try:
            if self.path.is_symlink() or self.path.parent.is_symlink():
                raise ProceduralSkillError("Link simbólico não permitido.")
            if not self.path.exists():
                self._state, self._error = "missing", "Arquivo de habilidades ausente."
                return
            if not self.path.is_file() or self.path.stat().st_size > self.MAX_FILE_BYTES:
                raise ProceduralSkillError("Arquivo ausente, inválido ou excessivamente grande.")
            document = json.loads(
                self.path.read_text(encoding="utf-8"),
                object_pairs_hook=self._unique_pairs,
                parse_constant=self._reject_constant,
            )
            if not isinstance(document, dict) or set(document) != self.TOP_FIELDS:
                raise ProceduralSkillError("Estrutura raiz inválida.")
            if document["schema"] != self.SCHEMA or document["version"] != self.VERSION:
                raise ProceduralSkillError("Schema/versão incompatível.")
            entries = document["skills"]
            if not isinstance(entries, list) or len(entries) > self.MAX_SKILLS:
                raise ProceduralSkillError("Lista de habilidades inválida.")
            definitions = {}
            for entry in entries:
                skill = self._validate_skill(entry)
                if skill["id"] in definitions:
                    raise ProceduralSkillError(f"ID duplicado: {skill['id']}")
                definitions[skill["id"]] = skill
            self._definitions = definitions
            self._state, self._error = "valid", None
        except Exception as exc:
            self._definitions = {}
            self._state = "invalid"
            self._error = f"{type(exc).__name__}: {str(exc)[:240]}"

    @property
    def valid(self) -> bool:
        return self._state == "valid"

    def get(self, skill_id: str) -> dict | None:
        item = self._definitions.get(skill_id)
        return deepcopy(item) if item is not None else None

    def definitions(self) -> list[dict]:
        return deepcopy(list(self._definitions.values()))

    def readiness(self, skill_id: str) -> dict:
        skill = self._definitions.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        blockers = []
        if not skill["enabled"]:
            blockers.append("skill_disabled")
        if skill["maturity_state"] not in {"operational", "specialized"}:
            blockers.append("maturity_not_operational")
        else:
            verifier = getattr(self.evidence_verifier, "verify_local", None)
            if not callable(verifier):
                blockers.append("evidence_verifier_unavailable")
            else:
                for reference in skill["evidence"]:
                    try:
                        verification = verifier(reference)
                    except Exception:
                        verification = None
                    if (
                        not isinstance(verification, dict)
                        or verification.get("valid") is not True
                        or verification.get("reference") != reference
                    ):
                        blockers.append(f"evidence_unverified:{reference}")
        registered = set()
        if self.orchestrator is None:
            blockers.append("orchestrator_unavailable")
        else:
            try:
                status = self.orchestrator.status()
                registered = {
                    item["id"] for item in status.get("registered_capabilities", [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
            except Exception:
                blockers.append("orchestrator_status_unavailable")
        for step in skill["steps"]:
            capability = self.capability_manifest.get(step["capability_id"])
            if capability is None:
                blockers.append(f"capability_missing:{step['capability_id']}")
                continue
            if not capability["enabled"]:
                blockers.append(f"capability_disabled:{step['capability_id']}")
            if step["capability_id"] not in registered:
                blockers.append(f"capability_not_runtime_bound:{step['capability_id']}")
        available_tools = set()
        if self.store is not None:
            try:
                available_tools = {
                    item.get("tool_id") for item in self.store.list_tools()
                    if isinstance(item, dict)
                }
            except Exception:
                blockers.append("tool_catalog_unavailable")
        for tool_id in skill["tools"]:
            if tool_id not in available_tools:
                blockers.append(f"required_tool_missing:{tool_id}")
        return {
            "skill_id": skill_id,
            "ready": not blockers,
            "blockers": blockers,
            "execution_performed": False,
        }

    def match_intent(self, intent: str, *, limit: int = 5) -> dict:
        """Return a deterministic lexical baseline; this is not semantic understanding."""
        if not isinstance(intent, str) or not intent.strip() or len(intent) > 4096:
            raise ValueError("intent precisa conter de 1 a 4096 caracteres.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 32:
            raise ValueError("limit precisa estar entre 1 e 32.")
        normalized = intent.casefold()
        matches = []
        for skill_id, skill in self._definitions.items():
            if any(term.casefold() in normalized for term in skill["exclusions"]):
                continue
            hits = [term for term in skill["intent_triggers"] if term.casefold() in normalized]
            if not hits:
                continue
            readiness = self.readiness(skill_id)
            matches.append({
                "skill_id": skill_id,
                "score": sum(len(term) for term in hits),
                "matched_triggers": hits,
                "readiness": readiness,
            })
        matches.sort(key=lambda item: (-item["score"], item["skill_id"]))
        return {
            "status": "matched" if matches else "no_match",
            "matches": matches[:limit],
            "selection_policy": "deterministic_phrase_overlap_v1",
            "semantic_recruitment": False,
            "execution_performed": False,
        }

    def plan(self, skill_id: str, inputs: dict | None = None, *, persist: bool = False) -> dict:
        """Build a gated declarative plan; never dispatches its steps."""
        skill = self._definitions.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        supplied = {} if inputs is None else inputs
        if not isinstance(supplied, dict):
            raise ValueError("inputs precisa ser um objeto.")
        schema = skill["input_schema"]
        unknown = set(supplied) - set(schema)
        missing = {
            key for key, descriptor in schema.items()
            if descriptor["required"] and key not in supplied
        }
        if unknown or missing:
            raise ValueError(f"Entradas inválidas; ausentes={sorted(missing)}, desconhecidas={sorted(unknown)}")
        self._validate_json_value(supplied)
        for key, value in supplied.items():
            expected = schema[key]["type"]
            valid = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(float(value)),
                "boolean": isinstance(value, bool),
                "object": isinstance(value, dict),
                "array": isinstance(value, list),
            }[expected]
            if not valid:
                raise ValueError(f"Tipo inválido para input.{key}; esperado {expected}.")
        gate = self.readiness(skill_id)
        result = {
            "status": "planned" if gate["ready"] else "blocked",
            "skill_id": skill_id,
            "skill_version": skill["version"],
            "steps": deepcopy(skill["steps"]) if gate["ready"] else [],
            "readiness": gate,
            "inputs": deepcopy(supplied),
            "execution_performed": False,
            "dispatch_performed": False,
        }
        if persist:
            if self.store is None:
                raise RuntimeError("KnowledgeStore indisponível para registrar o plano.")
            self.store.record_event("procedural_skill.plan", {
                "skill_id": skill_id,
                "skill_version": skill["version"],
                "status": result["status"],
                "blockers": gate["blockers"],
                "execution_performed": False,
            })
            result["event_recorded"] = True
        else:
            result["event_recorded"] = False
        return result

    def status(self) -> dict:
        count = len(self._definitions)
        enabled = sum(item["enabled"] for item in self._definitions.values())
        operational = sum(
            item["maturity_state"] in {"operational", "specialized"}
            for item in self._definitions.values()
        )
        return {
            "component": "ProceduralSkillRegistry",
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "state": self._state,
            "valid": self.valid,
            "error": self._error,
            "declared_count": count,
            "enabled_count": enabled,
            "operational_count": operational,
            "ready_count": sum(self.readiness(key)["ready"] for key in self._definitions),
            "code_loading_enabled": False,
            "execution_enabled": False,
            "semantic_recruitment": False,
        }
