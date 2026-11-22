"""Experimental, bounded selector for internally interesting learning objectives.

This is a research primitive, not a runtime agent or an execution engine.
It ranks candidate investigations by expected learning value, controllability,
transfer and relevance while explicitly discounting noisy novelty. It never
creates goals, writes memory, invokes tools, or authorizes actions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable


class InterestSelectionError(ValueError):
    """Invalid candidate, dependency graph, or resource budget."""


@dataclass(frozen=True)
class InterestBudget:
    max_runtime_ms: int
    max_ram_mb: int
    max_selected: int = 8

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("max_runtime_ms", self.max_runtime_ms, 86_400_000),
            ("max_ram_mb", self.max_ram_mb, 65_536),
            ("max_selected", self.max_selected, 256),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise InterestSelectionError(f"{name} deve ser inteiro.")
            if value < 1 or value > maximum:
                raise InterestSelectionError(f"{name} fora do limite permitido.")


@dataclass(frozen=True)
class InterestCandidate:
    candidate_id: str
    topic: str
    relevance: float
    novelty: float
    uncertainty: float
    controllability: float
    learning_progress: float
    expected_transfer: float
    noise_risk: float
    estimated_runtime_ms: int
    estimated_ram_mb: int
    dependencies: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class CognitiveInterestSelector:
    """Rank research opportunities without executing or persisting them.

    The score is deliberately multi-factor:
      relevance                  0.25
      novelty                    0.10
      reducible uncertainty      0.20 * uncertainty * controllability
      expected learning progress 0.25
      expected transfer          0.20
      noise-risk penalty         -0.20

    Novelty alone is weak evidence. Unpredictable/noisy opportunities are
    discounted, and uncertainty contributes only when it is plausibly
    reducible through a controllable investigation.
    """

    VERSION = "0.1.0"
    MAX_CANDIDATES = 256
    MAX_DEPENDENCIES = 20
    MAX_TOPIC_LENGTH = 240
    MAX_EVIDENCE_REFS = 20
    MAX_EVIDENCE_REF_LENGTH = 240
    WEIGHTS = {
        "relevance": 0.25,
        "novelty": 0.10,
        "reducible_uncertainty": 0.20,
        "learning_progress": 0.25,
        "expected_transfer": 0.20,
        "noise_risk_penalty": -0.20,
    }

    @staticmethod
    def _unit(value: Any, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InterestSelectionError(f"{field} deve ser número entre 0 e 1.")
        value = float(value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise InterestSelectionError(f"{field} deve ser número finito entre 0 e 1.")
        return value

    @staticmethod
    def _bounded_int(value: Any, field: str, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise InterestSelectionError(f"{field} deve ser inteiro.")
        if value < 0 or value > maximum:
            raise InterestSelectionError(f"{field} fora do limite permitido.")
        return value

    @classmethod
    def _parse_candidate(cls, raw: Any) -> InterestCandidate:
        if not isinstance(raw, dict):
            raise InterestSelectionError("Cada candidato deve ser um objeto.")
        required = {
            "candidate_id", "topic", "relevance", "novelty", "uncertainty",
            "controllability", "learning_progress", "expected_transfer",
            "noise_risk", "estimated_runtime_ms", "estimated_ram_mb",
        }
        optional = {"dependencies", "evidence_refs"}
        if not required.issubset(raw) or set(raw) - required - optional:
            raise InterestSelectionError("Esquema de candidato incompatível.")

        candidate_id = raw["candidate_id"]
        topic = raw["topic"]
        if (not isinstance(candidate_id, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", candidate_id)):
            raise InterestSelectionError("candidate_id inválido.")
        if not isinstance(topic, str) or not topic.strip() or len(topic) > cls.MAX_TOPIC_LENGTH:
            raise InterestSelectionError("topic inválido.")

        dependencies = raw.get("dependencies", ())
        evidence_refs = raw.get("evidence_refs", ())
        if not isinstance(dependencies, (list, tuple)) or len(dependencies) > cls.MAX_DEPENDENCIES:
            raise InterestSelectionError("dependencies inválidas.")
        if any(not isinstance(item, str) or not item for item in dependencies):
            raise InterestSelectionError("Dependência precisa ser um ID não vazio.")
        if len(set(dependencies)) != len(dependencies) or candidate_id in dependencies:
            raise InterestSelectionError("Dependências duplicadas ou autorreferentes.")
        if not isinstance(evidence_refs, (list, tuple)) or len(evidence_refs) > cls.MAX_EVIDENCE_REFS:
            raise InterestSelectionError("evidence_refs inválidas.")
        if any(not isinstance(item, str) or not item or len(item) > cls.MAX_EVIDENCE_REF_LENGTH
               for item in evidence_refs):
            raise InterestSelectionError("Referência de evidência inválida.")

        return InterestCandidate(
            candidate_id=candidate_id,
            topic=topic.strip(),
            relevance=cls._unit(raw["relevance"], "relevance"),
            novelty=cls._unit(raw["novelty"], "novelty"),
            uncertainty=cls._unit(raw["uncertainty"], "uncertainty"),
            controllability=cls._unit(raw["controllability"], "controllability"),
            learning_progress=cls._unit(raw["learning_progress"], "learning_progress"),
            expected_transfer=cls._unit(raw["expected_transfer"], "expected_transfer"),
            noise_risk=cls._unit(raw["noise_risk"], "noise_risk"),
            estimated_runtime_ms=cls._bounded_int(
                raw["estimated_runtime_ms"], "estimated_runtime_ms", 86_400_000
            ),
            estimated_ram_mb=cls._bounded_int(
                raw["estimated_ram_mb"], "estimated_ram_mb", 65_536
            ),
            dependencies=tuple(dependencies),
            evidence_refs=tuple(evidence_refs),
        )

    @classmethod
    def _base_score(cls, item: InterestCandidate) -> float:
        score = (
            cls.WEIGHTS["relevance"] * item.relevance
            + cls.WEIGHTS["novelty"] * item.novelty
            + cls.WEIGHTS["reducible_uncertainty"] * item.uncertainty * item.controllability
            + cls.WEIGHTS["learning_progress"] * item.learning_progress
            + cls.WEIGHTS["expected_transfer"] * item.expected_transfer
            + cls.WEIGHTS["noise_risk_penalty"] * item.noise_risk
        )
        return round(min(1.0, max(0.0, score)), 8)

    @staticmethod
    def _topological_closure(
        root_id: str, candidates: dict[str, InterestCandidate]
    ) -> tuple[str, ...]:
        order: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(candidate_id: str) -> None:
            if candidate_id not in candidates:
                raise InterestSelectionError(
                    f"Dependência ausente: {candidate_id} (requerida por {root_id})."
                )
            if candidate_id in visiting:
                raise InterestSelectionError("Ciclo detectado no grafo de dependências.")
            if candidate_id in visited:
                return
            visiting.add(candidate_id)
            for dependency in sorted(candidates[candidate_id].dependencies):
                visit(dependency)
            visiting.remove(candidate_id)
            visited.add(candidate_id)
            order.append(candidate_id)

        visit(root_id)
        return tuple(order)

    def select(
        self,
        candidates: Iterable[dict[str, Any]],
        budget: InterestBudget,
        *,
        minimum_score: float = 0.05,
    ) -> dict[str, Any]:
        """Return a deterministic, explainable plan; never executes candidates."""
        if not isinstance(budget, InterestBudget):
            raise InterestSelectionError("budget deve ser InterestBudget.")
        minimum_score = self._unit(minimum_score, "minimum_score")
        if not isinstance(candidates, (list, tuple)) or len(candidates) > self.MAX_CANDIDATES:
            raise InterestSelectionError("Lista de candidatos inválida ou acima do limite.")

        parsed = [self._parse_candidate(item) for item in candidates]
        by_id = {item.candidate_id: item for item in parsed}
        if len(by_id) != len(parsed):
            raise InterestSelectionError("candidate_id duplicado.")

        # Validate every graph, including candidates that may not be selected.
        closures = {
            item.candidate_id: self._topological_closure(item.candidate_id, by_id)
            for item in parsed
        }
        ranked = sorted(
            parsed,
            key=lambda item: (-self._base_score(item), item.candidate_id),
        )

        selected_roots: list[str] = []
        selected_order: list[str] = []
        selected_set: set[str] = set()
        total_runtime = 0
        total_ram = 0
        rejected: list[dict[str, str]] = []

        for item in ranked:
            base_score = self._base_score(item)
            if base_score < minimum_score:
                rejected.append({"candidate_id": item.candidate_id, "reason": "below_minimum_score"})
                continue
            if item.candidate_id in selected_set:
                continue

            closure = closures[item.candidate_id]
            new_ids = [candidate_id for candidate_id in closure if candidate_id not in selected_set]
            proposed_count = len(selected_set) + len(new_ids)
            proposed_runtime = total_runtime + sum(by_id[c].estimated_runtime_ms for c in new_ids)
            proposed_ram = total_ram + sum(by_id[c].estimated_ram_mb for c in new_ids)

            if proposed_count > budget.max_selected:
                rejected.append({"candidate_id": item.candidate_id, "reason": "aggregate_count_budget"})
                continue
            if proposed_runtime > budget.max_runtime_ms:
                rejected.append({"candidate_id": item.candidate_id, "reason": "aggregate_runtime_budget"})
                continue
            if proposed_ram > budget.max_ram_mb:
                rejected.append({"candidate_id": item.candidate_id, "reason": "aggregate_ram_budget"})
                continue

            selected_roots.append(item.candidate_id)
            selected_order.extend(new_ids)
            selected_set.update(new_ids)
            total_runtime = proposed_runtime
            total_ram = proposed_ram

        score_records = []
        for item in ranked:
            score_records.append({
                "candidate_id": item.candidate_id,
                "topic": item.topic,
                "score": self._base_score(item),
                "factors": {
                    "relevance": item.relevance,
                    "novelty": item.novelty,
                    "reducible_uncertainty": round(item.uncertainty * item.controllability, 8),
                    "learning_progress": item.learning_progress,
                    "expected_transfer": item.expected_transfer,
                    "noise_risk": item.noise_risk,
                },
                "selected": item.candidate_id in selected_set,
                "evidence_refs": list(item.evidence_refs),
                "evidence_state": "caller_declared_unverified" if item.evidence_refs else "no_evidence_refs",
            })

        payload = {
            "schema_version": 1,
            "selector_version": self.VERSION,
            "status": "planned" if selected_roots else "abstain",
            "selected_roots": selected_roots,
            "execution_performed": False,
            "authorization_granted": False,
            "selected_order": selected_order,
            "aggregate_cost": {
                "runtime_ms": total_runtime,
                "ram_mb": total_ram,
                "selected_count": len(selected_set),
            },
            "budget": {
                "max_runtime_ms": budget.max_runtime_ms,
                "max_ram_mb": budget.max_ram_mb,
                "max_selected": budget.max_selected,
            },
            "ranking": score_records,
            "rejected": rejected,
            "limitations": [
                "Scores are heuristic priorities, not calibrated probabilities or emotions.",
                "Candidate estimates and evidence references are caller-declared and unauthenticated.",
                "The selector does not discover interests, create goals, persist memory, or execute work.",
                "Novelty is weakly weighted and noisy unpredictability is penalized to reduce noisy-TV behavior.",
                "A selected plan is not evidence that learning occurred or that transfer was achieved.",
            ],
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload["plan_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return payload
