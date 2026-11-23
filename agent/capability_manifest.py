"""Manifesto declarativo de capacidades do Mahoraga."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path


class CapabilityManifest:
    SCHEMA = "mahoraga.capability_manifest"
    VERSION = "1.0.0"
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

    FIELDS = {
        "id", "name", "purpose", "description", "version",
        "risk", "maturity_state", "source_module", "operations",
        "inputs", "outputs", "dependencies", "tools", "limitations",
        "resource_requirements", "validation", "enabled", "metadata",
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

    @classmethod
    def _validate_definition(cls, item):
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

            if document["version"] != self.VERSION:
                raise ValueError("Versão incompatível.")

            entries = document["capabilities"]
            if not isinstance(entries, list) or len(entries) > 256:
                raise ValueError("Lista de capacidades inválida.")

            definitions = {}
            for entry in entries:
                definition = self._validate_definition(entry)
                capability_id = definition["id"]

                if capability_id in definitions:
                    raise ValueError(f"ID duplicado: {capability_id}")

                definitions[capability_id] = definition

            self._definitions = definitions
            self._state = "valid"
            self._error = None

        except Exception as exc:
            self._definitions = {}
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
            "version": self.VERSION,
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
