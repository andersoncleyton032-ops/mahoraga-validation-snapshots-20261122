"""Adaptadores explícitos e limitados para capacidades somente de leitura.

A construção de bindings não registra nem ativa capacidades. O caminho de
execução governado adiciona verificações cooperativas fornecidas pelo
ResearchOrchestrator.
"""

from __future__ import annotations

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
        """Require the Orchestrator's cooperative context before and after work."""
        def invoke(*args, execution_context, **kwargs):
            check = getattr(execution_context, "check", None)
            if not callable(check):
                raise TypeError(
                    "execution_context precisa fornecer check() cooperativo."
                )
            check()
            result = function(*args, **kwargs)
            check()
            return result

        invoke.__name__ = "governed_" + capability_id.replace(".", "_")
        invoke.__doc__ = (
            f"Vínculo governado para {capability_id}; "
            "exige ExecutionContext fornecido pelo ResearchOrchestrator."
        )
        return invoke

    def build_governed_bindings(self) -> dict[str, Callable[..., Any]]:
        """Build context-aware callables; this does not register or activate them."""
        raw = self.build_bindings()
        return {
            capability_id: self._governed_binding(capability_id, function)
            for capability_id, function in raw.items()
        }
