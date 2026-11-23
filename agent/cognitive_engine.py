"""Integrated cognitive coordination for Mahoraga.

Coordinates persistent memory, observations, hypotheses, experiments
and provenance-linked knowledge. It does not claim that imported text
has been learned by the neural network.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .dharma import Dharma
from .knowledge_engine import KnowledgeEngine
from .memory import get_store
from .metacognition import MetacognitiveMonitor
from .memory_graph import MemoryGraphEngine
from .prototype_plasticity import PrototypePlasticity


class CognitiveEngine:
    VERSION = "0.2.0"

    def __init__(
        self, store=None, knowledge=None, dharma=None, introspection=None,
        reasoning=None,
        approval_verifier=None,
        evidence_verifier=None,
    ):
        self.store = store or get_store()
        self.knowledge = knowledge or KnowledgeEngine(self.store)
        self.dharma = dharma or Dharma()
        self.introspection = introspection
        # Trust providers are injected by a trusted host integration. No
        # caller-supplied boolean is accepted as a substitute.
        self.approval_verifier = (
            approval_verifier
            if approval_verifier is not None
            else getattr(self.dharma, "approval_verifier", None)
        )
        if approval_verifier is not None:
            self.dharma.approval_verifier = approval_verifier
        self.evidence_verifier = evidence_verifier
        if reasoning is None:
            from .reasoning_engine import ReasoningEngine
            reasoning = ReasoningEngine(self)
        self.reasoning = reasoning
        if getattr(self.reasoning, "cognitive", self) is not self:
            raise ValueError("ReasoningEngine precisa compartilhar este CognitiveEngine.")
        from .mathematics_engine import MathematicsEngine
        self.mathematics = MathematicsEngine()
        from .adaptive_learning import AdaptiveLearning
        self.adaptive_learning = AdaptiveLearning(self)
        from .executive_engine import ExecutiveEngine
        self.executive = ExecutiveEngine(self)
        from .conversation_engine import ConversationMemoryEngine
        self.conversation = ConversationMemoryEngine(self)
        self.prototype_plasticity = PrototypePlasticity(self)
        self.metacognition = MetacognitiveMonitor(self)
        self.memory_graph = MemoryGraphEngine(self)

    def _authorize(self, action: str, target: str = ""):
        decision = self.dharma.evaluate(action, target=target)

        if not decision.allowed:
            raise PermissionError(decision.reason)

        return decision

    def _event(self, event_type: str, payload: dict[str, Any]):
        self.store.record_event(
            event_type=event_type,
            payload=payload,
            severity="info",
        )

    def status(self) -> dict[str, Any]:
        self._authorize("introspect")

        return {
            "component": "CognitiveEngine",
            "version": self.VERSION,
            "storage": self.store.counts(),
            "knowledge": self.knowledge.counts(),
            "neural_training": "not_automatically_connected",
            "reasoning": self.reasoning.status(),
            "mathematics": self.mathematics.status(),
            "prototype_plasticity": self.prototype_plasticity.status(),
            "metacognition": self.metacognition.status(),
            "memory_graph": self.memory_graph.status(),
        }

    def metacognitive_report(
        self, limit: int = 500, bins: int = 10,
        task: str | None = None, predictor_id: str | None = None,
    ) -> dict[str, Any]:
        """Calcula calibração usando somente episódios com evidência verificada."""
        self._authorize("introspect")
        return self.metacognition.report(
            limit=limit, bins=bins, task=task, predictor_id=predictor_id
        )

    def assess_confidence(
        self,
        confidence: float,
        *,
        task: str | None = None,
        predictor_id: str | None = None,
        minimum_samples: int = 20,
        minimum_confidence: float = 0.65,
        maximum_ece: float = 0.15,
        minimum_bin_samples: int = 5,
    ) -> dict[str, Any]:
        """Avalia se há base calibrada para responder ou se abster; não autoriza ações."""
        self._authorize("local_compute")
        return self.metacognition.assess(
            confidence,
            task=task,
            predictor_id=predictor_id,
            minimum_samples=minimum_samples,
            minimum_confidence=minimum_confidence,
            maximum_ece=maximum_ece,
            minimum_bin_samples=minimum_bin_samples,
        )

    def predict_prototype(self, features: Any) -> dict[str, Any]:
        """Classifica um vetor usando protótipos adaptativos persistentes."""
        return self.prototype_plasticity.predict(features)

    def learn_prototype(
        self,
        features: Any,
        label: str,
        *,
        approved: bool = False,
        evidence: list[str] | None = None,
        source: str = "human_feedback",
        approval_attestation: Any = None,
        evidence_attestation: Any = None,
    ) -> dict[str, Any]:
        """Aprende um protótipo com atestados confiáveis e de uso único."""
        return self.prototype_plasticity.learn_one(
            features,
            label,
            approved=approved,
            evidence=evidence,
            source=source,
            approval_attestation=approval_attestation,
            evidence_attestation=evidence_attestation,
        )

    def reason(
        self,
        facts,
        rules,
        contradiction_pairs=None,
        persist: bool = False,
    ) -> dict[str, Any]:
        """Executa raciocínio local sob a política Dharma compartilhada."""
        if not isinstance(persist, bool):
            raise ValueError("persist deve ser booleano.")
        self._authorize("local_compute")
        return self.reasoning.reason(
            facts=facts,
            rules=rules,
            contradiction_pairs=contradiction_pairs,
            persist=persist,
        )

    def evaluate_math(
        self,
        expression: str,
        variables: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Avalia uma expressão matemática exata sob a política Dharma."""
        self._authorize("local_compute")
        return self.mathematics.evaluate_expression(expression, variables)

    def solve_linear_equation(
        self,
        equation: str,
        variable: str | None = None,
    ) -> dict[str, Any]:
        """Resolve e verifica por substituição uma equação linear exata."""
        self._authorize("local_compute")
        return self.mathematics.solve_linear_equation(equation, variable)

    def solve_linear_system(
        self,
        equations: list[str],
        variables: list[str] | None = None,
    ) -> dict[str, Any]:
        """Resolve um sistema linear exato sob a política Dharma."""
        self._authorize("local_compute")
        return self.mathematics.solve_linear_system(equations, variables)


    def trace_memory_paths(
        self,
        source_event_id: int,
        target_event_id: int,
        *,
        predicate: str | None = None,
        direction: str = "outgoing",
        max_hops: int = 4,
        max_paths: int = 10,
        max_edge_visits: int = 5000,
        history_limit: int = 1000,
    ) -> dict[str, Any]:
        """Expose read-only, bounded relation paths through the shared memory graph."""
        return self.memory_graph.trace_paths(
            source_event_id,
            target_event_id,
            predicate=predicate,
            direction=direction,
            max_hops=max_hops,
            max_paths=max_paths,
            max_edge_visits=max_edge_visits,
            history_limit=history_limit,
        )

    def retrieve_knowledge(
        self,
        query: str,
        limit: int = 5,
        subject: str | None = None,
        max_candidates: int = 1000,
        include_associations: bool = False,
        max_associated_events: int = 10,
    ) -> dict[str, Any]:
        """Recupera conhecimento e, opcionalmente, expande associações episódicas.

        A operação é somente leitura: não treina a rede neural, não promove
        fragmentos a fatos e preserva a proveniência entregue pelo KnowledgeEngine.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query deve ser texto não vazio.")
        if len(query) > 500:
            raise ValueError("query excede 500 caracteres.")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 20
        ):
            raise ValueError("limit deve ser um inteiro entre 1 e 20.")
        if (
            isinstance(max_candidates, bool)
            or not isinstance(max_candidates, int)
            or not 1 <= max_candidates <= 5000
        ):
            raise ValueError("max_candidates deve ser um inteiro entre 1 e 5000.")
        if subject is not None and (
            not isinstance(subject, str)
            or not subject.strip()
            or len(subject) > 120
        ):
            raise ValueError("subject deve ser texto não vazio com até 120 caracteres.")
        if not isinstance(include_associations, bool):
            raise ValueError("include_associations deve ser booleano.")
        if (
            isinstance(max_associated_events, bool)
            or not isinstance(max_associated_events, int)
            or not 0 <= max_associated_events <= 50
        ):
            raise ValueError("max_associated_events deve estar entre 0 e 50.")

        decision = self._authorize("read_project")
        matches = self.knowledge.search_chunks(
            query=query,
            limit=limit,
            subject=subject,
            max_candidates=max_candidates,
        )
        associations = (
            self.memory_graph.expand_chunk_associations(
                matches, max_related_events=max_associated_events
            )
            if include_associations and matches else {
                "status": "not_requested" if not include_associations else "no_matches",
                "association_count": 0,
                "related_event_count": 0,
                "associations": [],
                "persistent_write_performed": False,
                "all_associations_unverified": True,
            }
        )
        return {
            "status": "retrieved" if matches else "no_match",
            "query": query,
            "subject": subject,
            "ranking_method": "bm25_lexical_v1",
            "knowledge_status": "prepared_not_learned",
            "result_count": len(matches),
            "matches": matches,
            "associations": associations,
            "authorization": asdict(decision),
            "neural_training_performed": False,
            "memory_modified": False,
        }

    def record_observation(
        self,
        category: str,
        subject: str,
        data: Any,
        source: str,
        confidence: float | None = None,
        limitations: list[str] | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize("record_observation")

        self.store.record_observation(
            category=category,
            subject=subject,
            data=data,
            source=source,
            confidence=confidence,
            limitations=limitations,
        )

        self._event(
            "cognitive.observation.recorded",
            {
                "category": category,
                "subject": subject,
                "source": source,
            },
        )

        return {
            "status": "recorded",
            "decision": asdict(decision),
        }

    def record_learning(
        self,
        key: str,
        learning: Any,
        source: str = "internal",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize("record_learning")

        if not isinstance(key, str) or not key.strip():
            raise ValueError("A chave da aprendizagem não pode estar vazia.")

        if not isinstance(source, str) or not source.strip():
            raise ValueError("A origem da aprendizagem não pode estar vazia.")

        details = dict(metadata or {})
        details.update({
            "kind": "cognitive_learning",
            "source": source,
            "engine_version": self.VERSION,
        })

        self.store.save_memory(
            key=key.strip(),
            value=learning,
            metadata=details,
        )

        self._event(
            "cognitive.learning.recorded",
            {
                "key": key.strip(),
                "source": source,
            },
        )

        return {
            "status": "recorded",
            "key": key.strip(),
            "decision": asdict(decision),
        }

    def propose_hypothesis(
        self,
        hypothesis: str,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize("record_experiment")

        if not isinstance(hypothesis, str) or not hypothesis.strip():
            raise ValueError("A hipótese não pode estar vazia.")

        if not isinstance(question, str) or not question.strip():
            raise ValueError("A pergunta de investigação não pode estar vazia.")

        cycle_id = uuid.uuid4().hex

        self._event(
            "cognitive.hypothesis.proposed",
            {
                "cycle_id": cycle_id,
                "hypothesis": hypothesis.strip(),
                "question": question.strip(),
                "context": context or {},
                "status": "proposed_not_tested",
            },
        )

        return {
            "cycle_id": cycle_id,
            "status": "proposed_not_tested",
            "decision": asdict(decision),
        }

    def complete_experiment(
        self,
        hypothesis: str,
        method: str,
        result: str,
        conclusion: str,
        metadata: dict[str, Any] | None = None,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize("record_experiment")

        fields = {
            "hypothesis": hypothesis,
            "method": method,
            "result": result,
            "conclusion": conclusion,
        }

        for name, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} não pode estar vazio.")

        details = dict(metadata or {})
        if cycle_id is not None:
            details["cognitive_cycle_id"] = cycle_id

        self.store.record_experiment(
            hypothesis=hypothesis.strip(),
            method=method.strip(),
            result=result.strip(),
            conclusion=conclusion.strip(),
            metadata=details,
        )

        self._event(
            "cognitive.experiment.completed",
            {
                "cycle_id": cycle_id,
                "conclusion": conclusion.strip(),
            },
        )

        return {
            "status": "recorded",
            "cycle_id": cycle_id,
            "decision": asdict(decision),
        }

    def prepare_document_learning(
        self,
        document_id: int,
        chunk_limit: int = 10000,
    ) -> dict[str, Any]:
        self._authorize("read_project")

        documents = self.knowledge.list_documents(limit=1000)
        document = next(
            (item for item in documents if item["id"] == document_id),
            None,
        )

        if document is None:
            raise ValueError("Documento não encontrado no catálogo.")

        chunks = self.knowledge.list_chunks(
            document_id=document_id,
            limit=chunk_limit,
        )

        if not chunks:
            raise ValueError("O documento não possui fragmentos disponíveis.")

        return {
            "document": document,
            "chunks": chunks,
            "status": "prepared_not_learned",
            "neural_training_performed": False,
        }

    def review_initiatives(self, experience_limit: int = 200) -> dict[str, Any]:
        """Synthesize initiative candidates from existing learning and capability reviews."""
        return self.executive.review_initiatives(
            experience_limit=experience_limit
        )

    def adopt_initiative(
        self, candidate_id: str, *, approved: bool = False
    ) -> dict[str, Any]:
        """Adopt a freshly revalidated initiative as a planned goal after approval."""
        return self.executive.adopt_initiative(
            candidate_id, approved=approved
        )

    def review_context(
        self,
        topic: str | None = None,
        event_limit: int = 50,
        experiment_limit: int = 50,
        knowledge_query: str | None = None,
    ) -> dict[str, Any]:
        self._authorize("introspect")

        if not 1 <= event_limit <= 500:
            raise ValueError("event_limit deve estar entre 1 e 500.")

        if not 1 <= experiment_limit <= 500:
            raise ValueError("experiment_limit deve estar entre 1 e 500.")

        if knowledge_query is not None and (
            not isinstance(knowledge_query, str) or not knowledge_query.strip()
        ):
            raise ValueError("knowledge_query deve ser texto não vazio ou None.")

        memories = self.store.load_memories()
        events = self.store.list_events(limit=event_limit)
        experiments = self.store.list_experiments(limit=experiment_limit)
        documents = self.knowledge.list_documents(
            subject=topic,
            limit=100,
        )

        knowledge_matches = []
        if knowledge_query is not None:
            self._authorize("read_project")
            knowledge_matches = self.knowledge.search_chunks(
                knowledge_query,
                limit=10,
            )

        if topic:
            term = topic.casefold()

            memories = {
                key: value
                for key, value in memories.items()
                if term in key.casefold()
                or term in json.dumps(value, ensure_ascii=False, default=str).casefold()
            }

            events = [
                item for item in events
                if term in json.dumps(item, ensure_ascii=False, default=str).casefold()
            ]

            experiments = [
                item for item in experiments
                if term in json.dumps(item, ensure_ascii=False, default=str).casefold()
            ]

        return {
            "topic": topic,
            "memories": memories,
            "events": events,
            "experiments": experiments,
            "documents": documents,
            "knowledge_query": knowledge_query,
            "knowledge_matches": knowledge_matches,
        }



    def recall_experiences(
        self,
        task: str,
        *,
        context: dict[str, Any] | None = None,
        limit: int = 5,
        min_similarity: float = 0.5,
    ) -> dict[str, Any]:
        """Recall bounded prior episodes without modifying memory or authorizing tools."""
        return self.adaptive_learning.retrieve_experiences(
            task,
            context=context,
            limit=limit,
            min_similarity=min_similarity,
        )

    def record_experience(self, *args, **kwargs):
        """Registra um episódio no mecanismo adaptativo compartilhado."""
        return self.adaptive_learning.record_experience(*args, **kwargs)

    def record_research_result(self, **kwargs) -> dict[str, Any]:
        """Attach a caller-reported research result to adaptive episodic memory."""
        return self.adaptive_learning.record_research_result(**kwargs)

    def review_experiences(self, limit: int = 200) -> dict[str, Any]:
        """Reavalia episódios e propõe padrões sem consolidá-los automaticamente."""
        return self.adaptive_learning.review_experiences(limit=limit)

    def consolidate_experience(
        self, candidate_id: str, *, approved: bool = False,
        approval_attestation: Any = None,
    ) -> dict:
        """Promove um padrão somente com atestado confiável de uso único."""
        return self.adaptive_learning.consolidate_candidate(
            candidate_id, approved=approved,
            approval_attestation=approval_attestation,
        )

    def review_capabilities(
        self,
        limit_experiments: int = 50,
        persist: bool = False,
    ) -> dict[str, Any]:
        """Cruza a cognição com a auditoria de capacidades, sem executar ferramentas."""
        self._authorize("introspect")

        if self.introspection is None:
            raise RuntimeError("IntrospectionEngine não conectado.")

        if not isinstance(limit_experiments, int) or isinstance(limit_experiments, bool):
            raise ValueError("limit_experiments deve ser um inteiro entre 1 e 500.")

        if not 1 <= limit_experiments <= 500:
            raise ValueError("limit_experiments deve estar entre 1 e 500.")

        audit = self.introspection.audit_capabilities(
            limit_experiments=limit_experiments,
            persist=persist,
        )

        if not isinstance(audit, dict):
            raise TypeError("A auditoria deve retornar um dicionário.")

        recommendations = audit.get("recommendations", [])
        if not isinstance(recommendations, list):
            recommendations = []

        candidates = []
        for item in recommendations:
            if not isinstance(item, dict):
                continue

            candidates.append({
                "tool_id": item.get("tool_id"),
                "priority": item.get("priority", "unspecified"),
                "reason": str(item.get("reason", "")),
                "proposed_action": str(item.get("action", "")),
                "status": "candidate_not_tested",
                "registered": False,
            })

        tools = audit.get("tools", [])
        if not isinstance(tools, list):
            tools = []

        limitations = audit.get("limitations", [])
        if not isinstance(limitations, list):
            limitations = []

        return {
            "status": "reviewed",
            "audit": audit,
            "assessment": {
                "tool_count": audit.get("tool_count", len(tools)),
                "evidence_sufficient_count": audit.get(
                    "evidence_sufficient_count", 0
                ),
                "evidence_insufficient_count": audit.get(
                    "evidence_insufficient_count", 0
                ),
                "recommendation_count": len(recommendations),
                "limitations": limitations,
                "candidate_hypotheses": candidates,
            },
            "execution_performed": False,
            "hypotheses_registered": False,
        }
