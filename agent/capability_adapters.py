"""Adaptadores explícitos e limitados para capacidades somente de leitura.

A construção de bindings não registra nem ativa capacidades. O caminho de
execução governado adiciona verificações cooperativas fornecidas pelo
ResearchOrchestrator.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable


class ReadOnlyCapabilityAdapters:
    """Prepara adaptadores explícitos para componentes de um IntegratedCore."""

    CAPABILITY_IDS = (
        "hardware.snapshot",
        "knowledge.catalog_read",
        "memory.history_read",
        "cognition.context_review",
        "introspection.self_model_read",
        "introspection.capability_audit",
        "research.status_read",
    )

    def __init__(self, core: Any):
        required = (
            "store",
            "hardware",
            "knowledge",
            "tools",
            "cognitive",
            "introspection",
            "research_orchestrator",
        )
        missing = [name for name in required if not hasattr(core, name)]
        if missing:
            raise ValueError(
                "IntegratedCore incompleto: " + ", ".join(missing)
            )

        self.core = core
        self._validate_shared_components()

    @staticmethod
    def _bounded_limit(value: int, field: str, maximum: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= maximum
        ):
            raise ValueError(f"{field} deve ser um inteiro entre 1 e {maximum}.")
        return value

    def _validate_shared_components(self) -> None:
        core = self.core
        checks = {
            "cognitive_store": core.cognitive.store is core.store,
            "knowledge_store": core.knowledge.store is core.store,
            "introspection_store": core.introspection.store is core.store,
            "introspection_hardware": (
                core.introspection.hardware is core.hardware
            ),
            "introspection_tools": (
                core.introspection.tools is core.tools
            ),
            "orchestrator_store": (
                core.research_orchestrator.store is core.store
            ),
        }
        failed = [name for name, valid in checks.items() if not valid]
        if failed:
            raise RuntimeError(
                "Componentes compartilhados inconsistentes: "
                + ", ".join(failed)
            )

    def hardware_snapshot(self) -> dict:
        return self.core.hardware.snapshot()

    def knowledge_catalog_read(
        self,
        subject: str | None = None,
        document_id: int | None = None,
        document_limit: int = 50,
        chunk_limit: int = 200,
    ) -> dict:
        self._bounded_limit(document_limit, "document_limit", 100)
        self._bounded_limit(chunk_limit, "chunk_limit", 200)
        if subject is not None and (
            not isinstance(subject, str) or not subject.strip() or len(subject) > 120
        ):
            raise ValueError("subject deve ser texto não vazio com até 120 caracteres.")
        documents = self.core.knowledge.list_documents(
            subject=subject,
            limit=document_limit,
        )
        chunks = []
        if document_id is not None:
            chunks = self.core.knowledge.list_chunks(
                document_id=document_id,
                limit=chunk_limit,
            )

        return {
            "documents": documents,
            "chunks": chunks,
            "counts": self.core.knowledge.counts(),
        }

    def memory_history_read(
        self,
        memory_limit: int = 100,
        event_limit: int = 100,
        event_type: str | None = None,
    ) -> dict:
        """Expose bounded history envelopes, never memory values or event payloads."""
        self._bounded_limit(memory_limit, "memory_limit", 100)
        self._bounded_limit(event_limit, "event_limit", 200)
        counts = self.core.store.counts()
        memory_catalog = self.core.store.list_memory_metadata(limit=memory_limit)
        memory_count = self.core.store.count_memories()
        events = self.core.store.list_event_metadata(
            limit=event_limit,
            event_type=event_type,
        )
        event_count = (
            self.core.store.count_events(event_type=event_type)
            if event_type is not None else counts["events"]
        )
        return {
            "memory_catalog": memory_catalog,
            "memory_count": memory_count,
            "memory_window_limit": memory_limit,
            "memory_window_truncated": memory_count > len(memory_catalog),
            "events": events,
            "event_count": event_count,
            "event_window_limit": event_limit,
            "event_window_truncated": event_count > len(events),
            "experiment_count": counts["experiments"],
            "payloads_exposed": False,
        }

    def cognition_context_review(
        self,
        topic: str | None = None,
        event_limit: int = 50,
    ) -> dict:
        self._bounded_limit(event_limit, "event_limit", 100)
        if topic is not None and (
            not isinstance(topic, str) or not topic.strip() or len(topic) > 120
        ):
            raise ValueError("topic deve ser texto não vazio com até 120 caracteres.")
        # A consulta é intencionalmente metadata-only: o review_context original
        # carrega todos os valores de memória e payloads, sem limite de memória.
        self.core.cognitive._authorize("introspect")
        counts = self.core.store.counts()
        memory_catalog = self.core.store.list_memory_metadata(limit=50)
        event_catalog = self.core.store.list_event_metadata(limit=event_limit)
        document_catalog = self.core.knowledge.list_documents(
            subject=topic,
            limit=50,
        )
        memory_count = self.core.store.count_memories()
        event_count = counts["events"]
        return {
            "component": "CognitiveEngine",
            "status": "metadata_reviewed",
            "topic": topic.strip() if topic is not None else None,
            "memory_catalog": memory_catalog,
            "memory_count": memory_count,
            "memory_window_truncated": memory_count > len(memory_catalog),
            "event_catalog": event_catalog,
            "event_count": event_count,
            "event_window_truncated": event_count > len(event_catalog),
            "document_catalog": document_catalog,
            "document_window_truncated": (
                counts.get("documents", 0) > len(document_catalog)
                if topic is None else None
            ),
            "counts": counts,
            "payloads_exposed": False,
            "execution_performed": False,
        }

    def introspection_self_model_read(self) -> dict:
        # O valor é fixado aqui; não é fornecido pelo chamador.
        return self.core.introspection.build_self_model(persist=False)

    def introspection_capability_audit(
        self,
        limit_experiments: int = 50,
    ) -> dict:
        self._bounded_limit(limit_experiments, "limit_experiments", 100)
        # O valor é fixado aqui; não é fornecido pelo chamador.
        return self.core.introspection.audit_capabilities(
            limit_experiments=limit_experiments,
            persist=False,
        )

    def research_status_read(self) -> dict:
        return self.core.research_orchestrator.status()

    def build_bindings(self) -> dict[str, Callable[..., Any]]:
        """Cria um mapa experimental em memória, sem registrar capacidades."""
        bindings = {
            "hardware.snapshot": self.hardware_snapshot,
            "knowledge.catalog_read": self.knowledge_catalog_read,
            "memory.history_read": self.memory_history_read,
            "cognition.context_review": self.cognition_context_review,
            "introspection.self_model_read": (
                self.introspection_self_model_read
            ),
            "introspection.capability_audit": (
                self.introspection_capability_audit
            ),
            "research.status_read": self.research_status_read,
        }

        if set(bindings) != set(self.CAPABILITY_IDS):
            raise RuntimeError("Conjunto de adaptadores inconsistente.")

        return bindings

    @staticmethod
    def _governed_binding(
        capability_id: str,
        function: Callable[..., Any],
    ) -> Callable[..., Any]:
        """Require a cooperative context and persist a compact result checkpoint."""
        def invoke(*args, execution_context, **kwargs):
            check = getattr(execution_context, "check", None)
            checkpoint = getattr(execution_context, "checkpoint", None)
            if not callable(check) or not callable(checkpoint):
                raise TypeError(
                    "execution_context precisa fornecer check() e checkpoint()."
                )
            check()
            result = function(*args, **kwargs)
            try:
                encoded = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError, RecursionError) as exc:
                raise ValueError(
                    f"Resultado não é JSON válido: {capability_id}"
                ) from exc
            if len(encoded) > 65_536:
                raise ValueError(
                    f"Resultado excede 65536 bytes: {capability_id}"
                )
            checkpoint({
                "capability_id": capability_id,
                "result_sha256": hashlib.sha256(encoded).hexdigest(),
                "result_bytes": len(encoded),
                "result_type": type(result).__name__,
                "completed": True,
            })
            check()
            return result

        invoke.__name__ = "governed_" + capability_id.replace(".", "_")
        invoke.__doc__ = (
            f"Vínculo governado para {capability_id}; "
            "exige ExecutionContext e checkpoint fornecidos pelo ResearchOrchestrator."
        )
        return invoke

    def build_governed_bindings(self) -> dict[str, Callable[..., Any]]:
        """Build context-aware callables; this does not register or activate them."""
        raw = self.build_bindings()
        return {
            capability_id: self._governed_binding(capability_id, function)
            for capability_id, function in raw.items()
        }

    def register_enabled(self) -> dict:
        """Register only explicitly enabled read-only adapters from the manifest."""
        orchestrator = self.core.research_orchestrator
        manifest = getattr(orchestrator, "capability_manifest", None)
        if manifest is None or getattr(manifest, "valid", False) is not True:
            return {
                "status": "blocked",
                "registered": [],
                "blockers": ["capability_manifest_unavailable_or_invalid"],
                "execution_performed": False,
            }

        bindings = self.build_governed_bindings()
        candidates = []
        blockers = []
        for capability_id, function in bindings.items():
            declared = manifest.get(capability_id)
            if not isinstance(declared, dict):
                blockers.append(f"capability_not_declared:{capability_id}")
                continue
            if declared.get("enabled") is not True:
                continue
            if declared.get("risk") != "read_only":
                blockers.append(f"adapter_risk_not_read_only:{capability_id}")
                continue
            resources = declared.get("resource_requirements")
            if not isinstance(resources, dict):
                blockers.append(f"resource_contract_missing:{capability_id}")
                continue
            seconds = resources.get("estimated_runtime_seconds")
            ram_mb = resources.get("estimated_ram_mb")
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, (int, float))
                or not math.isfinite(float(seconds))
                or not 0 < seconds <= 20
                or isinstance(ram_mb, bool)
                or not isinstance(ram_mb, (int, float))
                or not math.isfinite(float(ram_mb))
                or not 0 < ram_mb <= 256
            ):
                blockers.append(f"resource_contract_invalid:{capability_id}")
                continue
            candidates.append((capability_id, function, float(seconds), float(ram_mb)))

        if blockers:
            return {
                "status": "blocked",
                "registered": [],
                "blockers": blockers,
                "execution_performed": False,
            }
        if not candidates:
            return {
                "status": "no_enabled_capabilities",
                "registered": [],
                "blockers": [],
                "execution_performed": False,
            }

        try:
            sync_result = orchestrator.sync_manifest_catalog()
        except Exception:
            return {
                "status": "blocked",
                "registered": [],
                "blockers": ["manifest_catalog_sync_failed"],
                "execution_performed": False,
            }
        conflicts = (
            sync_result.get("conflicts", [])
            if isinstance(sync_result, dict) else []
        )
        conflicting_ids = {
            item.get("id") for item in conflicts if isinstance(item, dict)
        }
        registered = []
        for capability_id, function, seconds, ram_mb in candidates:
            if capability_id in conflicting_ids:
                blockers.append(f"manifest_catalog_conflict:{capability_id}")
                continue
            existing = orchestrator.capability_descriptor(capability_id)
            if existing is not None:
                compatible = (
                    existing.get("risk") == "read_only"
                    and existing.get("estimated_runtime_seconds") == seconds
                    and existing.get("estimated_ram_mb") == ram_mb
                    and existing.get("checkpointable") is True
                )
                if not compatible:
                    blockers.append(f"runtime_binding_conflict:{capability_id}")
                    continue
                registered.append(capability_id)
                continue
            try:
                result = orchestrator.register_capability(
                    capability_id,
                    function,
                    risk="read_only",
                    description=f"Governed read-only adapter for {capability_id}.",
                    estimated_runtime_seconds=seconds,
                    estimated_ram_mb=ram_mb,
                    checkpointable=True,
                )
            except Exception:
                blockers.append(f"runtime_registration_failed:{capability_id}")
                continue
            if not isinstance(result, dict) or result.get("registered") is not True:
                blockers.append(f"runtime_registration_unconfirmed:{capability_id}")
                continue
            registered.append(capability_id)

        return {
            "status": "registered" if registered and not blockers else "partial" if registered else "blocked",
            "registered": registered,
            "blockers": blockers,
            "execution_performed": False,
        }
