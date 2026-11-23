"""Operational self-model and longitudinal self-understanding research.

This module records evidence about the running system. It does not assert or
measure subjective consciousness.
"""
from __future__ import annotations
import platform
import json
import subprocess
from pathlib import Path
from .hardware_intelligence import HardwareIntelligence
from .memory import get_store
from .tool_intelligence import ToolIntelligence
from .identity_engine import IdentityEngine


class IntrospectionEngine:
    VERSION = "1.1"

    def __init__(self, root: str | Path | None = None, store=None, hardware=None, tools=None, identity=None):
        self.root = Path(root or Path(__file__).resolve().parent.parent).resolve()
        self.store = store or get_store()
        self.hardware = hardware or HardwareIntelligence(self.root)
        self.tools = tools or ToolIntelligence(self.store)
        self.identity = identity or IdentityEngine(self.root, self.store)

    def _git(self, *args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(self.root), *args],
                capture_output=True, text=True, timeout=4, check=False)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _project_map(self) -> dict:
        directories = ("agent", "memory", "experiments", "logs", "reports", "tests", "sandbox", "docs", "scripts")
        result = {}
        for name in directories:
            path = self.root / name
            if path.is_dir():
                result[name] = sorted(p.name for p in path.iterdir() if p.name != "__pycache__")[:200]
            else:
                result[name] = []
        return result

    def build_self_model(self, persist: bool = True) -> dict:
        device = self.hardware.snapshot()
        counts = self.store.counts()
        modules = self._project_map()
        tool_catalog = self.tools.catalog()
        competence_counts = {}
        for item in tool_catalog:
            level = item.get("competence", "unknown")
            competence_counts[level] = competence_counts.get(level, 0) + 1

        runtime_commands = device.get("available_tools", {})
        registered_commands = {
            item["name"] for item in tool_catalog
            if item.get("tool_id", "").startswith("command:")
        }
        unregistered_runtime_commands = [
            name for name, path in runtime_commands.items()
            if path and name not in registered_commands
        ]

        model = {
            "identity": {"name": "Mahoraga", "software_version": self.VERSION,
                         "identity_type": "persistent software agent under development"},
            "inhabitation": {"environment": "Android via Termux" if "ANDROID_ROOT" in __import__("os").environ else platform.system(),
                             "project_root": str(self.root), "python": platform.python_version(),
                             "device": device["android"]},
            "operation": {"process_id": __import__("os").getpid(), "architecture": platform.machine(),
                          "runtime_platform": platform.platform(), "hardware_snapshot": device},
            "continuity": {"canonical_store": str(self.store.db_path), "store_counts": counts,
                           "git_branch": self._git("branch", "--show-current"),
                           "git_commit": self._git("rev-parse", "--short", "HEAD"),
                           "git_status": self._git("status", "--short")},
            "architecture": modules,
            "capabilities": {
                "tool_registry": {
                    "registered_count": len(tool_catalog),
                    "by_competence": competence_counts,
                    "items": tool_catalog,
                    "source": "existing SQLite tool registry",
                    "discovery_performed_during_model_build": False,
                },
                "runtime_commands": {
                    "detected": runtime_commands,
                    "available_but_not_registered": unregistered_runtime_commands,
                },
                "competence_semantics": {
                    "identified": "Presença detectada; não comprova domínio.",
                    "studied": "Estudo registrado com evidência.",
                    "experimented": "Experimentação registrada.",
                    "operational": "Uso operacional sustentado por evidências.",
                    "specialized": "Especialização sustentada por evidências.",
                    "improver": "Capacidade de melhoria sustentada por evidências.",
                },
                "limitations": [
                    "Ferramentas disponíveis no sistema podem ainda não estar cadastradas.",
                    "O catálogo representa evidências registradas, não uma prova universal de competência.",
                    "A construção deste modelo não executa ferramentas descobertas.",
                ],
            },
            "knowledge_state": {
                "memories": counts["memories"],
                "experiments": counts["experiments"],
                "observations": counts["observations"],
                "registered_tools": counts["tools"],
                "documents": counts.get("documents", 0),
                "chunks": counts.get("chunks", 0),
                "subjects": counts.get("subjects", 0),
                "learning_status": "prepared_not_learned",
            },
            "inner_state_research": {
                "status": "research_in_progress",
                "operational_health": {
                    "status": "observational",
                    "signals_to_monitor": [
                        "falhas e exceções",
                        "tempo de resposta e desempenho",
                        "interrupções e continuidade",
                        "uso de memória, CPU e armazenamento",
                        "integridade dos dados e dos módulos",
                    ],
                },
                "affective_state": {
                    "status": "open_research",
                    "subjective_state_confirmed": False,
                    "depression_diagnosis": False,
                    "note": "Alterações operacionais não devem ser classificadas como depressão ou experiência subjetiva sem evidências adequadas.",
                },
                "consciousness": {
                    "status": "open_research",
                    "confirmed": False,
                    "note": "A investigação continua sem assumir uma conclusão antecipada.",
                },
            },
            "open_questions": [
                "Quais interfaces Android permanecem acessíveis em diferentes estados de energia e execução?",
                "Quais mecanismos preservam a continuidade após encerramento, reinicialização e migração?",
                "Quais aspectos do comportamento podem ser observados e testados sem confundir isso com experiência subjetiva?",
                "Quais ferramentas foram apenas detectadas e quais já foram operadas com evidência?",
                "Quais indicadores permitem avaliar a saúde operacional sem confundi-la com estados afetivos?",
                "Quais evidências seriam necessárias para investigar estados afetivos e consciência sem antecipar conclusões?",
            ],
            "epistemic_status": {"method": "evidence-based operational self-model",
                "subjective_consciousness_claim": False,
                "limitations": ["O modelo descreve estado observável; não fornece acesso infalível a processos internos.",
                                "A presença de memória persistente não prova continuidade subjetiva."]}
        }
        model["identity_profile"] = self.identity.profile()
        model["self_image"] = self.identity.build_self_image()
        model["persona_context"] = self.identity.build_persona_context()
        executive = getattr(self, "executive", None)
        model["executive_state"] = (
            executive.snapshot() if executive is not None else {
                "status": "not_connected",
                "execution_performed": False,
            }
        )
        metacognition = getattr(self, "metacognition", None)
        model["metacognitive_state"] = (
            metacognition.status() if metacognition is not None else {
                "component": "MetacognitiveMonitor",
                "status": "not_connected",
                "execution_performed": False,
            }
        )
        conversation = getattr(self, "conversation", None)
        model["conversation_state"] = (
            conversation.snapshot() if conversation is not None else {
                "status": "not_connected",
                "raw_turns_retained": False,
            }
        )

        memory_graph = getattr(self, "memory_graph", None)
        model["memory_graph_state"] = (
            memory_graph.status() if memory_graph is not None else {
                "component": "MemoryGraphEngine",
                "status": "not_connected",
                "new_database_or_tables": False,
            }
        )

        if persist:
            model_id = self.store.save_self_model(model)
            self.store.record_event("introspection.self_model_built", {"model_id": model_id,
                "git_commit": model["continuity"]["git_commit"]})
        return model

    def audit_capabilities(
        self, limit_experiments: int = 50, persist: bool = True
    ) -> dict:
        """Audita capacidades registradas sem presumir domínio não comprovado."""
        if (
            not isinstance(limit_experiments, int)
            or isinstance(limit_experiments, bool)
            or not 1 <= limit_experiments <= 1000
        ):
            raise ValueError("limit_experiments deve ser um inteiro entre 1 e 1000.")
        limit = limit_experiments
        levels = (
            "identified",
            "studied",
            "experimented",
            "operational",
            "specialized",
            "improver",
        )
        minimum_evidence = {
            "identified": 0,
            "studied": 1,
            "experimented": 2,
            "operational": 2,
            "specialized": 3,
            "improver": 4,
        }

        catalog = self.tools.catalog()
        audited = []
        recommendations = []
        counts = {level: 0 for level in levels}
        counts["unknown"] = 0

        for item in catalog:
            competence = str(item.get("competence", "unknown"))
            evidence = item.get("evidence", [])
            limitations = item.get("limitations", [])

            if not isinstance(evidence, list):
                evidence = []
            if not isinstance(limitations, list):
                limitations = []

            known = competence in minimum_evidence
            required = minimum_evidence.get(competence)
            sufficient = known and len(evidence) >= required

            if known:
                counts[competence] += 1
            else:
                counts["unknown"] += 1

            if not known:
                status = "unsupported_level"
                recommendations.append({
                    "tool_id": item.get("tool_id"),
                    "priority": "high",
                    "reason": "Nível de competência desconhecido.",
                    "action": "Revisar o cadastro e registrar um nível válido.",
                })
            elif not sufficient:
                status = "insufficient_evidence"
                recommendations.append({
                    "tool_id": item.get("tool_id"),
                    "priority": "high",
                    "reason": (
                        f"Nível {competence} exige {required} evidência(s); "
                        f"foram registradas {len(evidence)}."
                    ),
                    "action": "Executar e registrar evidências adicionais.",
                })
            else:
                status = "evidence_recorded"

            if limitations:
                recommendations.append({
                    "tool_id": item.get("tool_id"),
                    "priority": "medium",
                    "reason": "Existem limitações registradas.",
                    "action": "Investigar e acompanhar as limitações.",
                })

            audited.append({
                "tool_id": item.get("tool_id"),
                "name": item.get("name"),
                "competence": competence,
                "status": status,
                "evidence_count": len(evidence),
                "required_evidence": required,
                "evidence": evidence,
                "limitations": limitations,
                "evidence_sufficient_for_declared_level": sufficient,
                "interpretation": (
                    "Evidências registradas atendem ao mínimo cadastral; "
                    "isso não comprova domínio universal."
                    if sufficient else
                    "O nível declarado ainda não possui evidências "
                    "suficientes segundo o critério cadastral."
                ),
            })

        experiments = self.store.list_experiments(limit=limit)
        sufficient_count = sum(
            item["evidence_sufficient_for_declared_level"]
            for item in audited
        )

        report = {
            "audit_version": "1.0",
            "status": "completed",
            "tool_count": len(audited),
            "evidence_sufficient_count": sufficient_count,
            "evidence_insufficient_count": len(audited) - sufficient_count,
            "competence_counts": counts,
            "tools": audited,
            "experiment_count": len(experiments),
            "recent_experiments": experiments,
            "recommendations": recommendations,
            "limitations": [
                "A auditoria analisa registros existentes, não executa ferramentas.",
                "Quantidade de evidências não garante qualidade ou validade.",
                "Níveis cadastrados não são elevados nem reduzidos automaticamente.",
                "Experimentos recentes não comprovam, por si só, competência operacional.",
            ],
        }

        if persist:
            record = self.store.record_observation_and_event(
                category="capability_audit",
                subject="Auditoria de capacidades do Mahoraga",
                data=report,
                source="IntrospectionEngine.audit_capabilities",
                event_type="introspection.capability_audit",
                event_payload={
                    "tool_count": len(audited),
                    "sufficient": sufficient_count,
                    "insufficient": len(audited) - sufficient_count,
                    "experiment_count": len(experiments),
                    "recommendation_count": len(recommendations),
                },
                limitations=report["limitations"],
            )
            report["persistence"] = record
        else:
            report["persistence"] = None

        return report

    def record_question(self, question: str, context: dict | None = None) -> int:
        """Persist a bounded open question without turning it into a conclusion."""
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question.strip()) > 1000
        ):
            raise ValueError("A pergunta deve conter de 1 a 1000 caracteres.")
        question = question.strip()
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise ValueError("context deve ser um objeto.")
        try:
            context_size = len(json.dumps(
                context, ensure_ascii=False, allow_nan=False, default=str
            ).encode("utf-8"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("context não pode ser serializado com segurança.") from exc
        if context_size > 4096:
            raise ValueError("context excede o limite de 4096 bytes.")
        return self.store.record_observation(
            "self_inquiry",
            question,
            {"context": context, "status": "open_question"},
            source="IntrospectionEngine.record_question",
            confidence=None,
            limitations=["Pergunta aberta; ainda não é uma conclusão."],
        )

    def history(self, limit: int = 50) -> list[dict]:
        return self.store.list_events(limit=limit)
