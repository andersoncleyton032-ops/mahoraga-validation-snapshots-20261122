"""Manifesto declarativo de capacidades do Mahoraga."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from copy import deepcopy
from pathlib import Path


class CapabilityManifest:
    SCHEMA = "mahoraga.capability_manifest"
    VERSION = "1.1.0"
    SUPPORTED_VERSIONS = {"1.0.0", "1.1.0"}
    MAX_FILE_BYTES = 262144

    ALLOWED_RISKS = {"read_only", "local_compute"}

    ALLOWED_STATES = {
        "planned",
        "in_development",
        "implemented",
        "tested_individually",
        "tested_integration",
        "validated_real",
    }

    TOP_FIELDS = {"schema", "version", "capabilities"}

    CAPABILITY_CLASSES = {"observation_source", "cognitive_process", "tool_skill"}
    AVAILABILITY_MODES = {"on_demand", "environment_dependent", "runtime_bound"}
    AVAILABILITY_STATES = {"unknown", "available", "unavailable", "degraded"}

    FIELDS = {
        "id", "name", "purpose", "description", "version",
        "risk", "maturity_state", "source_module", "operations",
        "inputs", "outputs", "dependencies", "tools", "limitations",
        "resource_requirements", "validation", "enabled", "metadata",
        "capability_class", "supported_intents", "domains",
        "uncertainty_reduced", "classification_rationale", "availability",
        "capability_dependencies",
    }

    FORBIDDEN = {
        "callable", "function", "import_path", "module_path",
        "entrypoint", "code", "source_code", "python_code",
        "bytecode", "exec", "eval",
    }

    def __init__(self, path):
        self.path = Path(path)
        self._definitions = {}
        self._state = "missing"
        self._error = None
        self._version = None
        self._load()

    @staticmethod
    def _unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Chave JSON duplicada: {key}")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value):
        raise ValueError(f"Constante JSON inválida: {value}")

    @classmethod
    def _validate_values(cls, value, depth=0):
        if depth > 10:
            raise ValueError("Profundidade excessiva.")

        if value is None or isinstance(value, (str, bool, int)):
            if isinstance(value, str) and len(value) > 4096:
                raise ValueError("Texto muito longo.")
            return

        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Número não finito.")
            return

        if isinstance(value, list):
            if len(value) > 256:
                raise ValueError("Lista muito extensa.")
            for item in value:
                cls._validate_values(item, depth + 1)
            return

        if isinstance(value, dict):
            if len(value) > 256:
                raise ValueError("Objeto muito extenso.")

            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("Chave não textual.")

                normalized = key.strip().lower().replace("-", "_")
                if normalized in cls.FORBIDDEN:
                    raise ValueError(f"Campo executável proibido: {key}")

                cls._validate_values(item, depth + 1)
            return

        raise ValueError("Tipo de dado não permitido.")

    @staticmethod
    def _valid_id(value):
        allowed = (
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789._-"
        )
        return (
            isinstance(value, str)
            and 0 < len(value) <= 160
            and value == value.strip()
            and all(char in allowed for char in value)
        )

    @staticmethod
    def _validate_taxonomy_tags(value, field):
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= 16
            or any(
                not isinstance(tag, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", tag)
                for tag in value
            )
            or len(set(value)) != len(value)
        ):
            raise ValueError(f"Taxonomia inválida: {field}")

    @classmethod
    def _validate_availability(cls, value):
        expected = {
            "mode", "status", "evidence_source",
            "evidence_timestamp", "max_age_seconds",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Contrato de disponibilidade inválido.")
        if value["mode"] not in cls.AVAILABILITY_MODES:
            raise ValueError("Modo de disponibilidade desconhecido.")
        if value["status"] not in cls.AVAILABILITY_STATES:
            raise ValueError("Estado de disponibilidade desconhecido.")
        age = value["max_age_seconds"]
        if isinstance(age, bool) or not isinstance(age, int) or not 1 <= age <= 86400:
            raise ValueError("Janela de disponibilidade inválida.")
        source = value["evidence_source"]
        timestamp = value["evidence_timestamp"]
        if value["status"] == "unknown":
            if source is not None or timestamp is not None:
                raise ValueError("Disponibilidade desconhecida não pode declarar evidência.")
        else:
            if not isinstance(source, str) or not source.strip():
                raise ValueError("Disponibilidade observada exige fonte.")
            if not isinstance(timestamp, str) or not timestamp.strip():
                raise ValueError("Disponibilidade observada exige timestamp.")
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("Timestamp de disponibilidade inválido.") from exc
            if parsed.tzinfo is None:
                raise ValueError("Timestamp de disponibilidade deve conter fuso horário.")

    @staticmethod
    def _validate_cost_evidence(value):
        expected = {"estimate_status", "estimate_source", "measured_cost", "measured_at"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Proveniência de custo inválida.")
        if value["estimate_status"] not in {
            "engineering_estimate", "not_estimated", "measured"
        }:
            raise ValueError("Estado de estimativa de custo desconhecido.")
        if not isinstance(value["estimate_source"], str) or not value["estimate_source"].strip():
            raise ValueError("Fonte da estimativa de custo ausente.")
        measured = value["measured_cost"]
        measured_at = value["measured_at"]
        if value["estimate_status"] == "measured":
            if not isinstance(measured, dict) or not measured:
                raise ValueError("Custo medido exige valores medidos.")
            if not isinstance(measured_at, str) or not measured_at.strip():
                raise ValueError("Custo medido exige timestamp.")
        elif measured is not None or measured_at is not None:
            raise ValueError("Custo não medido não pode conter valores medidos.")

    @classmethod
    def _validate_definition(cls, item, schema_version="1.0.0"):
        if not isinstance(item, dict):
            raise ValueError("Capacidade precisa ser um objeto.")

        unknown = set(item) - cls.FIELDS
        if unknown:
            raise ValueError(
                "Campos desconhecidos: " + ", ".join(sorted(unknown))
            )

        capability_id = item.get("id")
        if not cls._valid_id(capability_id):
            raise ValueError("ID de capacidade inválido.")

        for field in ("name", "purpose", "risk", "maturity_state"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Campo obrigatório inválido: {field}")

        if item["risk"] not in cls.ALLOWED_RISKS:
            raise ValueError("Risco não permitido.")

        if item["maturity_state"] not in cls.ALLOWED_STATES:
            raise ValueError("Maturidade desconhecida.")

        if not isinstance(item.get("enabled"), bool):
            raise ValueError("enabled precisa ser booleano.")

        result = {
            "id": capability_id,
            "name": item["name"].strip(),
            "purpose": item["purpose"].strip(),
            "description": item.get("description", ""),
            "version": item.get("version", "0.1.0"),
            "risk": item["risk"],
            "maturity_state": item["maturity_state"],
            "source_module": item.get("source_module", ""),
            "operations": item.get("operations", []),
            "inputs": item.get("inputs", {}),
            "outputs": item.get("outputs", {}),
            "dependencies": item.get("dependencies", []),
            "tools": item.get("tools", []),
            "limitations": item.get("limitations", []),
            "resource_requirements": item.get(
                "resource_requirements", {}
            ),
            "validation": item.get("validation", {}),
            "enabled": item["enabled"],
            "metadata": item.get("metadata", {}),
        }

        for field in ("description", "version", "source_module"):
            if not isinstance(result[field], str):
                raise ValueError(f"Campo textual inválido: {field}")

        for field in ("operations", "dependencies", "tools", "limitations"):
            value = result[field]
            if not isinstance(value, list) or any(
                not isinstance(entry, str) for entry in value
            ):
                raise ValueError(f"Lista inválida: {field}")

        for field in (
            "inputs", "outputs", "resource_requirements",
            "validation", "metadata",
        ):
            if not isinstance(result[field], dict):
                raise ValueError(f"Objeto inválido: {field}")

        if schema_version == "1.1.0":
            required_taxonomy = {
                "capability_class", "supported_intents", "domains",
                "uncertainty_reduced", "classification_rationale", "availability",
                "capability_dependencies",
            }
            missing = required_taxonomy - set(item)
            if missing:
                raise ValueError("Taxonomia ausente: " + ", ".join(sorted(missing)))
            capability_class = item["capability_class"]
            if capability_class not in cls.CAPABILITY_CLASSES:
                raise ValueError("Classe de capacidade desconhecida.")
            for field in ("supported_intents", "domains", "uncertainty_reduced"):
                cls._validate_taxonomy_tags(item[field], field)
            rationale = item["classification_rationale"]
            if not isinstance(rationale, str) or not 20 <= len(rationale.strip()) <= 500:
                raise ValueError("Justificativa de classificação inválida.")
            cls._validate_availability(item["availability"])
            capability_dependencies = item["capability_dependencies"]
            if (
                not isinstance(capability_dependencies, list)
                or len(capability_dependencies) > 64
                or any(not cls._valid_id(dep) for dep in capability_dependencies)
                or len(set(capability_dependencies)) != len(capability_dependencies)
                or capability_id in capability_dependencies
            ):
                raise ValueError("Dependências de capacidade inválidas.")
            cost_evidence = result["resource_requirements"].get("cost_evidence")
            cls._validate_cost_evidence(cost_evidence)
            validation = result["validation"]
            for field in ("contract_tested", "runtime_bound", "operationally_verified"):
                if not isinstance(validation.get(field), bool):
                    raise ValueError("Estado de validação inválido: " + field)
            evidence = validation.get("evidence")
            if not isinstance(evidence, list) or len(evidence) > 64:
                raise ValueError("Lista de evidências de validação inválida.")
            if (validation["contract_tested"] or validation["runtime_bound"] or validation["operationally_verified"]) and not evidence:
                raise ValueError("Validação declarada exige evidência referenciada.")
            if validation["operationally_verified"] and not validation["runtime_bound"]:
                raise ValueError("Validação operacional exige binding de runtime.")
            result.update({
                "capability_class": capability_class,
                "supported_intents": deepcopy(item["supported_intents"]),
                "domains": deepcopy(item["domains"]),
                "uncertainty_reduced": deepcopy(item["uncertainty_reduced"]),
                "classification_rationale": rationale.strip(),
                "availability": deepcopy(item["availability"]),
                "capability_dependencies": deepcopy(capability_dependencies),
            })
        else:
            # Legacy v1.0 remains readable but is explicitly unclassified and
            # unavailable for contextual recruitment until manually migrated.
            result.update({
                "capability_class": "unclassified",
                "supported_intents": [],
                "domains": [],
                "uncertainty_reduced": [],
                "classification_rationale": "Legacy v1.0 definition; manual classification required.",
                "availability": {
                    "mode": "on_demand",
                    "status": "unknown",
                    "evidence_source": None,
                    "evidence_timestamp": None,
                    "max_age_seconds": 300,
                },
                "capability_dependencies": [],
            })
            result["validation"].setdefault("contract_tested", False)
            result["validation"].setdefault("runtime_bound", False)
            result["validation"].setdefault("operationally_verified", False)
            result["validation"].setdefault("evidence", [])
            result["resource_requirements"].setdefault("cost_evidence", {
                "estimate_status": "not_estimated",
                "estimate_source": "Legacy v1.0 provenance not recorded.",
                "measured_cost": None,
                "measured_at": None,
            })

        cls._validate_values(result)
        return result

    def _load(self):
        try:
            if self.path.is_symlink() or self.path.parent.is_symlink():
                raise ValueError("Link simbólico não permitido.")

            if not self.path.exists():
                self._state = "missing"
                self._error = "Manifesto ausente."
                return

            if not self.path.is_file():
                raise ValueError("Caminho não é arquivo.")

            if self.path.stat().st_size > self.MAX_FILE_BYTES:
                raise ValueError("Manifesto excede o tamanho máximo.")

            document = json.loads(
                self.path.read_text(encoding="utf-8"),
                object_pairs_hook=self._unique_pairs,
                parse_constant=self._reject_constant,
            )

            if not isinstance(document, dict):
                raise ValueError("Raiz precisa ser objeto.")

            if set(document) != self.TOP_FIELDS:
                raise ValueError("Estrutura raiz inválida.")

            if document["schema"] != self.SCHEMA:
                raise ValueError("Esquema incompatível.")

            if document["version"] not in self.SUPPORTED_VERSIONS:
                raise ValueError("Versão incompatível.")
            schema_version = document["version"]

            entries = document["capabilities"]
            if not isinstance(entries, list) or len(entries) > 256:
                raise ValueError("Lista de capacidades inválida.")

            definitions = {}
            for entry in entries:
                definition = self._validate_definition(entry, schema_version)
                capability_id = definition["id"]

                if capability_id in definitions:
                    raise ValueError(f"ID duplicado: {capability_id}")

                definitions[capability_id] = definition

            if schema_version == "1.1.0":
                for capability_id, definition in definitions.items():
                    for dependency in definition["capability_dependencies"]:
                        if dependency not in definitions:
                            raise ValueError(
                                f"Dependência de capacidade desconhecida: {capability_id} -> {dependency}"
                            )

                visiting = set()
                visited = set()

                def visit(capability_id):
                    if capability_id in visiting:
                        raise ValueError(
                            f"Ciclo de dependências de capacidades: {capability_id}"
                        )
                    if capability_id in visited:
                        return
                    visiting.add(capability_id)
                    for dependency in definitions[capability_id]["capability_dependencies"]:
                        visit(dependency)
                    visiting.remove(capability_id)
                    visited.add(capability_id)

                for capability_id in definitions:
                    visit(capability_id)

            self._definitions = definitions
            self._version = schema_version
            self._state = "valid"
            self._error = None

        except Exception as exc:
            self._definitions = {}
            self._version = None
            self._state = "invalid"
            self._error = f"{type(exc).__name__}: {str(exc)[:200]}"

    @property
    def valid(self):
        return self._state == "valid"

    def get(self, capability_id):
        value = self._definitions.get(capability_id)
        return deepcopy(value) if value is not None else None

    def definitions(self):
        return deepcopy(list(self._definitions.values()))

    def sync_to_catalog(self, store):
        if not self.valid:
            raise RuntimeError("Manifesto inválido: " + str(self._error))

        existing = {
            item["capability_id"]: item
            for item in store.list_capabilities()
        }

        inserted = []
        preserved = []
        conflicts = []

        for capability_id, definition in self._definitions.items():
            current = existing.get(capability_id)

            if current is not None:
                preserved.append(capability_id)
                differences = []

                if current["risk"] != definition["risk"]:
                    differences.append("risk")

                if current["enabled"] != definition["enabled"]:
                    differences.append("enabled")

                current_metadata = current.get("metadata", {})
                definition_metadata = definition.get("metadata", {})
                current_internal_write = (
                    current_metadata.get("writes_internal_state", False)
                    if isinstance(current_metadata, dict) else False
                )
                definition_internal_write = (
                    definition_metadata.get("writes_internal_state", False)
                    if isinstance(definition_metadata, dict) else False
                )
                if current_internal_write is not definition_internal_write:
                    differences.append("metadata.writes_internal_state")

                if differences:
                    conflicts.append({
                        "id": capability_id,
                        "fields": differences,
                    })
                continue

            persistent = {
                key: deepcopy(value)
                for key, value in definition.items()
                if key != "id"
            }

            store.upsert_capability(capability_id, persistent)
            inserted.append(capability_id)

        return {
            "inserted": inserted,
            "preserved_existing": preserved,
            "conflicts": conflicts,
            "inserted_count": len(inserted),
            "preserved_count": len(preserved),
            "conflict_count": len(conflicts),
            "executables_loaded": 0,
        }

    def status(self):
        count = len(self._definitions)
        enabled = sum(
            item["enabled"] for item in self._definitions.values()
        )

        return {
            "schema": self.SCHEMA,
            "version": self._version,
            "supported_versions": sorted(self.SUPPORTED_VERSIONS),
            "path": str(self.path),
            "state": self._state,
            "valid": self.valid,
            "error": self._error,
            "declared_count": count,
            "enabled_count": enabled,
            "disabled_count": count - enabled,
            "executable_bindings": 0,
            "code_loading_enabled": False,
        }
