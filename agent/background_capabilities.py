"""Small allowlisted internal capabilities for bounded background work."""
from __future__ import annotations

from typing import Any


class InternalBackgroundCapabilities:
    CAPABILITY_ID = "internal.adopt_next_inquiry"
    DESCRIPTION = (
        "Reconcile interrupted sensor-observation intents, review internal questions, "
        "and adopt at most one bounded investigation objective. No network, external "
        "tools or workspace writes."
    )
    ESTIMATED_RUNTIME_SECONDS = 8
    ESTIMATED_RAM_MB = 64

    def __init__(self, core):
        self.core = core

    def register(self) -> dict[str, Any]:
        orchestrator = self.core.research_orchestrator
        manifest = getattr(orchestrator, "capability_manifest", None)
        if manifest is None or getattr(manifest, "valid", False) is not True:
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "capability_manifest_unavailable_or_invalid",
            }

        declared = manifest.get(self.CAPABILITY_ID)
        if not isinstance(declared, dict):
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "capability_not_declared",
            }
        if declared.get("enabled") is not True:
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "capability_disabled_in_manifest",
            }
        if declared.get("risk") != "local_compute":
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "capability_risk_mismatch",
            }
        metadata = declared.get("metadata", {})
        if (
            not isinstance(metadata, dict)
            or metadata.get("writes_internal_state") is not True
        ):
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "capability_internal_write_scope_mismatch",
            }
        if any(
            metadata.get(flag) is not False
            for flag in (
                "external_effects_allowed",
                "network_access_allowed",
                "tool_dispatch_allowed",
            )
        ):
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "capability_side_effect_contract_mismatch",
            }
        resources = declared.get("resource_requirements")
        if (
            not isinstance(resources, dict)
            or resources.get("max_runtime_seconds") != self.ESTIMATED_RUNTIME_SECONDS
            or resources.get("max_ram_mb") != self.ESTIMATED_RAM_MB
            or resources.get("checkpointable") is not True
        ):
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "capability_resource_contract_mismatch",
            }

        sync_catalog = getattr(orchestrator, "sync_manifest_catalog", None)
        if not callable(sync_catalog):
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "manifest_catalog_sync_unavailable",
            }
        try:
            sync_result = sync_catalog()
        except Exception:
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "manifest_catalog_sync_failed",
            }
        conflicts = (
            sync_result.get("conflicts", [])
            if isinstance(sync_result, dict) else []
        )
        if any(
            isinstance(conflict, dict)
            and conflict.get("id") == self.CAPABILITY_ID
            for conflict in conflicts
        ):
            return {
                "status": "blocked",
                "registered": False,
                "capability_id": self.CAPABILITY_ID,
                "reason": "manifest_catalog_conflict",
            }

        existing = orchestrator.capability_descriptor(self.CAPABILITY_ID)
        if existing is not None:
            if (
                existing.get("risk") != "local_compute"
                or existing.get("checkpointable") is not True
                or existing.get("writes_internal_state") is not True
                or existing.get("external_effects_allowed") is not False
                or existing.get("network_access_allowed") is not False
                or existing.get("tool_dispatch_allowed") is not False
                or existing.get("estimated_runtime_seconds") != self.ESTIMATED_RUNTIME_SECONDS
                or existing.get("estimated_ram_mb") != self.ESTIMATED_RAM_MB
            ):
                raise PermissionError(
                    "Registro existente diverge do contrato interno checkpointable."
                )
            return {
                **existing,
                "status": "registered",
                "registered": True,
                "capability_id": self.CAPABILITY_ID,
            }
        registered = orchestrator.register_capability(
            self.CAPABILITY_ID,
            self._adopt_next_inquiry,
            risk="local_compute",
            description=self.DESCRIPTION,
            estimated_runtime_seconds=self.ESTIMATED_RUNTIME_SECONDS,
            estimated_ram_mb=self.ESTIMATED_RAM_MB,
            checkpointable=True,
            writes_internal_state=True,
            external_effects_allowed=False,
            network_access_allowed=False,
            tool_dispatch_allowed=False,
        )
        return {
            **registered,
            "status": "registered",
            "registered": True,
            "capability_id": self.CAPABILITY_ID,
        }

    def _adopt_next_inquiry(self, execution_context) -> dict[str, Any]:
        check = getattr(execution_context, "check", None)
        checkpoint = getattr(execution_context, "checkpoint", None)
        if not callable(check) or not callable(checkpoint):
            raise TypeError("A execução interna exige contexto checkpointable.")
        check()
        checkpoint({"phase": "before_perception_reconciliation", "capability": self.CAPABILITY_ID})
        perception = getattr(self.core, "perception", None)
        reconcile = getattr(perception, "reconcile_observation_intents", None)
        perception_reconciliation = {
            "status": "not_connected",
            "examined": 0,
            "completed": 0,
            "reopened": 0,
        }
        if callable(reconcile):
            perception_reconciliation = reconcile()
            if not isinstance(perception_reconciliation, dict):
                raise TypeError("A reconciliação perceptiva precisa retornar um dicionário.")
        check()
        checkpoint({
            "phase": "after_perception_reconciliation",
            "status": str(perception_reconciliation.get("status", "unknown"))[:80],
            "completed": perception_reconciliation.get("completed", 0),
            "reopened": perception_reconciliation.get("reopened", 0),
        })
        check()
        checkpoint({"phase": "before_review", "capability": self.CAPABILITY_ID})
        result = self.core.executive.adopt_next_internal_inquiry()
        if not isinstance(result, dict):
            raise TypeError("A adoção de iniciativa precisa retornar um dicionário.")
        if result.get("tool_dispatch_performed") is True:
            raise PermissionError("A capacidade interna não pode despachar ferramentas.")
        if result.get("external_effects_performed") is True:
            raise PermissionError("A capacidade interna não pode executar efeitos externos.")
        if result.get("network_access_performed") is True:
            raise PermissionError("A capacidade interna não pode acessar a rede.")
        check()
        checkpoint({
            "phase": "after_review",
            "status": str(result.get("status", "unknown"))[:80],
            "goal_created": result.get("goal_created") is True,
        })
        return {
            "status": str(result.get("status", "unknown"))[:80],
            "goal_created": result.get("goal_created") is True,
            "goal_id": result.get("goal_id"),
            "perception_reconciliation": perception_reconciliation,
            "tool_dispatch_performed": False,
            "external_effects_performed": False,
            "network_access_performed": False,
            "execution_performed": result.get("execution_performed") is True,
        }
