"""Motor determinístico de raciocínio lógico do Mahoraga.

Esta versão trabalha com fatos, regras explícitas, proveniência,
confiança e detecção de contradições. Não representa inteligência
geral nem aprendizagem neural.
"""

from __future__ import annotations

import math
from typing import Any


class ReasoningEngineError(ValueError):
    """Erro de validação do motor de raciocínio."""


class ReasoningEngine:
    VERSION = "0.1.0"

    MAX_FACTS = 200
    MAX_RULES = 200
    MAX_STEPS = 1000
    MAX_TEXT = 240

    LIMITATIONS = [
        "O raciocínio utiliza regras explícitas fornecidas na entrada.",
        "A ausência de um fato não significa que seu contrário seja verdadeiro.",
        "A confiança é um indicador informado, não uma probabilidade comprovada.",
        "Origens e confiança de fatos são declarações do chamador, não identidades autenticadas.",
        "Relatos repetidos não são tratados como evidências independentes nem aumentam confiança.",
        "Não há aprendizagem neural ou descoberta automática de regras.",
        "Nenhuma ação externa é executada.",
        "A política Dharma é aplicada pela fachada CognitiveEngine; o uso direto deste motor não substitui essa fronteira."
    ]

    def __init__(self, cognitive=None):
        self.cognitive = cognitive

    @staticmethod
    def _normalize(value: str) -> str:
        if not isinstance(value, str):
            raise ReasoningEngineError("A afirmação deve ser texto.")

        value = " ".join(value.strip().split())

        if not value or len(value) > ReasoningEngine.MAX_TEXT:
            raise ReasoningEngineError(
                "Afirmação vazia ou acima do limite permitido."
            )

        return value.casefold()

    @staticmethod
    def _confidence(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ReasoningEngineError("Confiança deve ser numérica.")

        try:
            value = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ReasoningEngineError("Confiança deve ser finita e estar entre 0 e 1.") from exc

        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ReasoningEngineError(
                "Confiança deve ser finita e estar entre 0 e 1."
            )

        return value

    def _parse_facts(self, facts):
        if not isinstance(facts, list) or len(facts) > self.MAX_FACTS:
            raise ReasoningEngineError("Lista de fatos inválida.")

        parsed = {}
        for item in facts:
            if isinstance(item, str):
                statement = item
                source = "input"
                confidence = 1.0
            elif isinstance(item, dict):
                statement = item.get("statement")
                source = item.get("source", "input")
                confidence = item.get("confidence", 1.0)
            else:
                raise ReasoningEngineError("Formato de fato inválido.")

            key = self._normalize(statement)
            if not isinstance(source, str) or not source.strip():
                raise ReasoningEngineError("Origem do fato inválida.")
            if len(source) > 100:
                raise ReasoningEngineError("Origem muito extensa.")

            source = source.strip()
            reported_confidence = self._confidence(confidence)
            report = {
                "source": source,
                "reported_confidence": reported_confidence,
                "source_identity_verified": False,
            }
            existing = parsed.get(key)
            if existing is None:
                parsed[key] = {
                    "statement": " ".join(statement.strip().split()),
                    "source": source,
                    "supporting_sources": [source],
                    "supporting_reports": [report],
                    "confidence": reported_confidence,
                    "confidence_aggregation": "minimum_reported_confidence",
                    "epistemic_state": "caller_reported_unverified",
                    "source_identity_verified": False,
                    "derived_from": [],
                }
                continue

            # Preserve every report, but do not count repetitions as independent
            # evidence or let repetition inflate the confidence value.
            existing["supporting_reports"].append(report)
            if source not in existing["supporting_sources"]:
                existing["supporting_sources"].append(source)
            existing["confidence"] = min(
                existing["confidence"], reported_confidence
            )

        return parsed

    def _parse_rules(self, rules):
        if not isinstance(rules, list) or len(rules) > self.MAX_RULES:
            raise ReasoningEngineError("Lista de regras inválida.")

        parsed = []

        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise ReasoningEngineError("Regra inválida.")

            premises = rule.get("if_all")
            conclusion = rule.get("then")
            source = rule.get("source", "explicit_rule")
            confidence = self._confidence(
                rule.get("confidence", 1.0)
            )

            if not isinstance(premises, list) or not 1 <= len(premises) <= 20:
                raise ReasoningEngineError(
                    "Cada regra precisa de 1 a 20 premissas."
                )

            normalized_premises = [
                self._normalize(value) for value in premises
            ]
            normalized_conclusion = self._normalize(conclusion)

            if not isinstance(source, str) or not source.strip():
                raise ReasoningEngineError("Origem da regra inválida.")

            if len(source) > 100:
                raise ReasoningEngineError("Origem da regra muito extensa.")

            parsed.append({
                "id": f"rule_{index + 1}",
                "if_all": normalized_premises,
                "then": normalized_conclusion,
                "source": source.strip(),
                "confidence": confidence
            })

        return parsed

    def _parse_contradictions(self, pairs):
        if pairs is None:
            return []

        if not isinstance(pairs, list) or len(pairs) > 100:
            raise ReasoningEngineError(
                "Lista de contradições inválida."
            )

        parsed = []

        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ReasoningEngineError(
                    "Cada contradição deve conter duas afirmações."
                )

            left = self._normalize(pair[0])
            right = self._normalize(pair[1])

            if left == right:
                raise ReasoningEngineError(
                    "Uma afirmação não pode contradizer a si mesma."
                )

            parsed.append((left, right))

        return parsed

    def reason(
        self,
        facts,
        rules,
        contradiction_pairs=None,
        persist=False
    ):
        """Executa encadeamento lógico com rastreabilidade."""

        known = self._parse_facts(facts)
        parsed_rules = self._parse_rules(rules)
        pairs = self._parse_contradictions(contradiction_pairs)

        initial_keys = set(known)
        steps = 0
        changed = True

        while changed and steps < self.MAX_STEPS:
            changed = False

            for rule in parsed_rules:
                premises = rule["if_all"]

                if not all(key in known for key in premises):
                    continue

                conclusion = rule["then"]

                if conclusion in known:
                    continue

                premise_confidence = min(
                    known[key]["confidence"] for key in premises
                )

                confidence = (
                    premise_confidence * rule["confidence"]
                )

                premise_evidence = [{
                    "statement": known[premise]["statement"],
                    "supporting_sources": list(
                        known[premise].get("supporting_sources", [known[premise].get("source")])
                    ),
                    "confidence": known[premise]["confidence"],
                    "epistemic_state": known[premise].get(
                        "epistemic_state", "derived_from_unverified_inputs"
                    ),
                } for premise in premises]
                supporting_sources = list(dict.fromkeys(
                    [rule["source"]] + [
                        source
                        for item in premise_evidence
                        for source in item["supporting_sources"]
                    ]
                ))
                known[conclusion] = {
                    "statement": conclusion,
                    "source": rule["source"],
                    "supporting_sources": supporting_sources,
                    "premise_evidence": premise_evidence,
                    "confidence": confidence,
                    "confidence_aggregation": "minimum_premise_confidence_times_rule_confidence",
                    "epistemic_state": "derived_from_unverified_inputs",
                    "source_identity_verified": False,
                    "derived_from": premises,
                    "rule_id": rule["id"]
                }

                steps += 1
                changed = True

                if steps >= self.MAX_STEPS:
                    break

        limit_reached = steps >= self.MAX_STEPS and changed

        contradictions = []

        for left, right in pairs:
            if left in known and right in known:
                contradictions.append({
                    "left": known[left]["statement"],
                    "right": known[right]["statement"],
                    "type": "explicit_contradiction"
                })

        derived = [
            dict(value)
            for key, value in known.items()
            if key not in initial_keys
        ]

        status = (
            "limit_reached" if limit_reached
            else "contradiction_detected" if contradictions
            else "completed"
        )

        result = {
            "engine": "ReasoningEngine",
            "version": self.VERSION,
            "status": status,
            "consistent": not bool(contradictions),
            "initial_fact_count": len(initial_keys),
            "total_fact_count": len(known),
            "derived_count": len(derived),
            "steps": steps,
            "facts": list(known.values()),
            "derived": derived,
            "contradictions": contradictions,
            "limitations": list(self.LIMITATIONS)
        }

        if persist:
            self._record_result(result)

        return result

    def _record_result(self, result):
        if self.cognitive is None:
            raise RuntimeError(
                "Núcleo cognitivo não foi conectado."
            )

        recorder = getattr(
            self.cognitive, "record_observation", None
        )

        if not callable(recorder):
            raise RuntimeError(
                "O núcleo cognitivo não oferece record_observation."
            )

        recorder(
            category="logical_reasoning",
            subject="reasoning_analysis",
            data={
                "status": result["status"],
                "consistent": result["consistent"],
                "initial_fact_count": result["initial_fact_count"],
                "derived_count": result["derived_count"],
                "contradiction_count": len(result["contradictions"]),
                "steps": result["steps"]
            },
            source="reasoning_engine",
            confidence=1.0,
            limitations=list(self.LIMITATIONS)
        )

    def demonstrate_capabilities(self):
        """Executa demonstrações isoladas, sem gravar na memória."""

        derivation = self.reason(
            facts=[
                {
                    "statement": "solo molhado",
                    "source": "sensor_simulado",
                    "confidence": 0.95
                }
            ],
            rules=[
                {
                    "if_all": ["solo molhado"],
                    "then": "risco de escorregamento",
                    "source": "regra demonstrativa",
                    "confidence": 0.90
                }
            ]
        )

        contradiction = self.reason(
            facts=[
                "porta aberta",
                "porta fechada"
            ],
            rules=[],
            contradiction_pairs=[
                ["porta aberta", "porta fechada"]
            ]
        )

        checks = {
            "logical_derivation": (
                derivation["derived_count"] == 1
                and derivation["derived"][0]["statement"]
                == "risco de escorregamento"
            ),
            "contradiction_detection": (
                len(contradiction["contradictions"]) == 1
            ),
            "provenance": (
                bool(derivation["derived"][0]["derived_from"])
            ),
            "confidence_tracking": (
                derivation["derived"][0]["confidence"] == 0.855
            )
        }

        return {
            "engine": "ReasoningEngine",
            "version": self.VERSION,
            "passed": all(checks.values()),
            "checks": checks,
            "demonstration": {
                "derivation": derivation,
                "contradiction": contradiction
            },
            "memory_modified": False,
            "external_actions": False
        }

    def status(self):
        return {
            "component": "ReasoningEngine",
            "version": self.VERSION,
            "available": True,
            "cognitive_connected": self.cognitive is not None,
            "logical_derivation": True,
            "contradiction_detection": True,
            "evidence_provenance": True,
            "source_identity_verified": False,
            "confidence_calibrated": False,
            "confidence_tracking": True,
            "neural_training": False,
            "autonomous_execution": False,
            "dharma_integration": False
        }
