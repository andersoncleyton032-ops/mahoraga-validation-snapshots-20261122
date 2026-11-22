"""Small allowlisted internal capabilities for bounded background work."""
from __future__ import annotations

from typing import Any


class InternalBackgroundCapabilities:
    CAPABILITY_ID = "internal.adopt_next_inquiry"
    DESCRIPTION = (
        "Review existing internal questions and adopt at most one bounded "
        "investigation objective. No network, external tools or workspace writes."
    )
    ESTIMATED_RUNTIME_SECONDS = 8
    ESTIMATED_RAM_MB = 64

    def __init__(self, core):
        self.core = core

    def register(self) -> dict[str, Any]:
        orchestrator = self.core.research_orchestrator
        existing = orchestrator.capability_descriptor(self.CAPABILITY_ID)
        if existing is not None:
            if (
                existing.get("risk") != "local_compute"
                or existing.get("checkpointable") is not True
                or existing.get("estimated_runtime_seconds") != self.ESTIMATED_RUNTIME_SECONDS
                or existing.get("estimated_ram_mb") != self.ESTIMATED_RAM_MB
            ):
                raise PermissionError(
                    "Registro existente diverge do contrato interno checkpointable."
                )
            return existing
        return orchestrator.register_capability(
            self.CAPABILITY_ID,
            self._adopt_next_inquiry,
            risk="local_compute",
            description=self.DESCRIPTION,
            estimated_runtime_seconds=self.ESTIMATED_RUNTIME_SECONDS,
            estimated_ram_mb=self.ESTIMATED_RAM_MB,
            checkpointable=True,
        )

    def _adopt_next_inquiry(self, execution_context) -> dict[str, Any]:
        check = getattr(execution_context, "check", None)
        checkpoint = getattr(execution_context, "checkpoint", None)
        if not callable(check) or not callable(checkpoint):
            raise TypeError("A execução interna exige contexto checkpointable.")
        check()
        checkpoint({"phase": "before_review", "capability": self.CAPABILITY_ID})
        result = self.core.executive.adopt_next_internal_inquiry()
        if not isinstance(result, dict):
            raise TypeError("A adoção de iniciativa precisa retornar um dicionário.")
        if result.get("tool_dispatch_performed") is True:
            raise PermissionError("A capacidade interna não pode despachar ferramentas.")
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
            "tool_dispatch_performed": False,
            "execution_performed": result.get("execution_performed") is True,
        }
