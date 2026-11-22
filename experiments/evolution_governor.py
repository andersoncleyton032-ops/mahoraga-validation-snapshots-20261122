"""Deterministic lifecycle governor for autonomous lab candidates.

Tracks candidate state and evidence only. It never executes code, accesses the
network, writes files, grants permissions, or promotes candidates to runtime.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any


class EvolutionGovernanceError(ValueError):
    """Invalid candidate metadata, evidence, transition, or budget."""


class CandidateStage(str, Enum):
    PROPOSED = "proposed"
    TRIAGED = "triaged"
    SANDBOXED = "sandboxed"
    TESTED = "tested"
    REVIEW_READY = "review_ready"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class EvolutionPolicy:
    max_active_candidates: int = 8
    max_runtime_seconds: int = 600
    max_memory_mb: int = 1024
    max_test_evaluations: int = 100_000

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("max_active_candidates", self.max_active_candidates, 64),
            ("max_runtime_seconds", self.max_runtime_seconds, 3600),
            ("max_memory_mb", self.max_memory_mb, 8192),
            ("max_test_evaluations", self.max_test_evaluations, 1_000_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise EvolutionGovernanceError(f"{name} must be an integer")
            if value < 1 or value > maximum:
                raise EvolutionGovernanceError(f"{name} is outside the permitted range")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    parent_digest: str
    change_scope: str
    risk_class: str
    estimated_runtime_seconds: int
    estimated_memory_mb: int
    estimated_test_evaluations: int
    external_effects: bool = False
    protected_target: bool = False
    stage: CandidateStage = CandidateStage.PROPOSED
    evidence: tuple[str, ...] = ()
    tests_passed: int | None = None
    tests_total: int | None = None
    candidate_digest: str | None = None


class EvolutionGovernor:
    """Fail-closed state machine; it is not an execution/deployment engine."""

    VERSION = "0.1.0"
    _TRANSITIONS = {
        CandidateStage.PROPOSED: {CandidateStage.TRIAGED, CandidateStage.REJECTED},
        CandidateStage.TRIAGED: {CandidateStage.SANDBOXED, CandidateStage.REJECTED},
        CandidateStage.SANDBOXED: {CandidateStage.TESTED, CandidateStage.REJECTED, CandidateStage.QUARANTINED},
        CandidateStage.TESTED: {CandidateStage.REVIEW_READY, CandidateStage.REJECTED, CandidateStage.QUARANTINED},
        CandidateStage.REVIEW_READY: {CandidateStage.QUARANTINED},
        CandidateStage.REJECTED: set(),
        CandidateStage.QUARANTINED: set(),
    }
    _RISK_CLASSES = {"low", "moderate", "high", "critical"}
    _DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")

    def __init__(self, policy: EvolutionPolicy | None = None) -> None:
        self.policy = policy or EvolutionPolicy()
        self._candidates: dict[str, Candidate] = {}

    @staticmethod
    def _nonempty(value: Any, field: str, maximum: int = 240) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise EvolutionGovernanceError(f"{field} must be a non-empty bounded string")
        return value.strip()

    @staticmethod
    def _bounded_int(value: Any, field: str, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise EvolutionGovernanceError(f"{field} must be an integer")
        if value < 0 or value > maximum:
            raise EvolutionGovernanceError(f"{field} is outside the permitted range")
        return value

    def register(self, *, candidate_id: str, parent_digest: str, change_scope: str,
                 risk_class: str, estimated_runtime_seconds: int, estimated_memory_mb: int,
                 estimated_test_evaluations: int, external_effects: bool = False,
                 protected_target: bool = False) -> Candidate:
        candidate_id = self._nonempty(candidate_id, "candidate_id", 80)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", candidate_id):
            raise EvolutionGovernanceError("candidate_id has invalid characters")
        if candidate_id in self._candidates:
            raise EvolutionGovernanceError("candidate_id already exists")
        if not isinstance(parent_digest, str) or not self._DIGEST_RE.fullmatch(parent_digest):
            raise EvolutionGovernanceError("parent_digest must be a SHA-256 hex digest")
        change_scope = self._nonempty(change_scope, "change_scope")
        if ("\\" in change_scope or "\x00" in change_scope
                or change_scope.startswith("/")):
            raise EvolutionGovernanceError("change_scope must be a relative lab path")
        scope_parts = change_scope.split("/")
        if (len(scope_parts) < 2
                or scope_parts[0] not in {"experiments", "tests", "docs"}
                or any(part in {"", ".", ".."} for part in scope_parts)):
            raise EvolutionGovernanceError("change_scope is outside permitted lab directories")
        if not isinstance(risk_class, str) or risk_class not in self._RISK_CLASSES:
            raise EvolutionGovernanceError("unknown risk_class")
        if not isinstance(external_effects, bool) or not isinstance(protected_target, bool):
            raise EvolutionGovernanceError("security flags must be booleans")
        if external_effects or protected_target:
            raise EvolutionGovernanceError("external effects and protected targets are forbidden")
        runtime = self._bounded_int(estimated_runtime_seconds, "estimated_runtime_seconds", 3600)
        memory = self._bounded_int(estimated_memory_mb, "estimated_memory_mb", 8192)
        evaluations = self._bounded_int(estimated_test_evaluations, "estimated_test_evaluations", 1_000_000)
        if runtime > self.policy.max_runtime_seconds:
            raise EvolutionGovernanceError("runtime estimate exceeds policy")
        if memory > self.policy.max_memory_mb:
            raise EvolutionGovernanceError("memory estimate exceeds policy")
        if evaluations > self.policy.max_test_evaluations:
            raise EvolutionGovernanceError("test evaluation estimate exceeds policy")
        active = sum(item.stage not in {CandidateStage.REJECTED, CandidateStage.QUARANTINED}
                     for item in self._candidates.values())
        if active >= self.policy.max_active_candidates:
            raise EvolutionGovernanceError("active candidate capacity exhausted")
        candidate = Candidate(candidate_id, parent_digest, change_scope, risk_class,
                              runtime, memory, evaluations)
        self._candidates[candidate_id] = candidate
        return candidate

    def transition(self, candidate_id: str, target: CandidateStage | str, *,
                   evidence_ref: str, tests_passed: int | None = None,
                   tests_total: int | None = None, candidate_digest: str | None = None) -> Candidate:
        if candidate_id not in self._candidates:
            raise EvolutionGovernanceError("unknown candidate")
        try:
            target = CandidateStage(target)
        except (TypeError, ValueError) as exc:
            raise EvolutionGovernanceError("unknown candidate stage") from exc
        current = self._candidates[candidate_id]
        if target not in self._TRANSITIONS[current.stage]:
            raise EvolutionGovernanceError(f"transition {current.stage.value} -> {target.value} is forbidden")
        evidence_ref = self._nonempty(evidence_ref, "evidence_ref")
        passed, total, digest = current.tests_passed, current.tests_total, current.candidate_digest
        if target == CandidateStage.TRIAGED and current.risk_class in {"high", "critical"}:
            raise EvolutionGovernanceError("high-risk candidates are not auto-admitted")
        if target == CandidateStage.TESTED:
            passed = self._bounded_int(tests_passed, "tests_passed", 1_000_000)
            total = self._bounded_int(tests_total, "tests_total", 1_000_000)
            if total == 0 or passed != total:
                raise EvolutionGovernanceError("all declared tests must pass before TESTED")
            if not isinstance(candidate_digest, str) or not self._DIGEST_RE.fullmatch(candidate_digest):
                raise EvolutionGovernanceError("candidate_digest must be a SHA-256 hex digest")
            digest = candidate_digest
        elif tests_passed is not None or tests_total is not None or candidate_digest is not None:
            raise EvolutionGovernanceError("test metrics are accepted only on TESTED transition")
        if target == CandidateStage.REVIEW_READY:
            if current.tests_total is None or not evidence_ref.startswith("independent-review:"):
                raise EvolutionGovernanceError("independent review evidence is required")
        updated = Candidate(
            candidate_id=current.candidate_id, parent_digest=current.parent_digest,
            change_scope=current.change_scope, risk_class=current.risk_class,
            estimated_runtime_seconds=current.estimated_runtime_seconds,
            estimated_memory_mb=current.estimated_memory_mb,
            estimated_test_evaluations=current.estimated_test_evaluations,
            external_effects=current.external_effects, protected_target=current.protected_target,
            stage=target, evidence=current.evidence + (evidence_ref,),
            tests_passed=passed, tests_total=total, candidate_digest=digest,
        )
        self._candidates[candidate_id] = updated
        return updated

    def get(self, candidate_id: str) -> Candidate:
        try:
            return self._candidates[candidate_id]
        except KeyError as exc:
            raise EvolutionGovernanceError("unknown candidate") from exc

    def snapshot(self) -> dict[str, Any]:
        records = []
        for key in sorted(self._candidates):
            item = asdict(self._candidates[key])
            item["stage"] = self._candidates[key].stage.value
            item["evidence"] = list(self._candidates[key].evidence)
            records.append(item)
        payload = {
            "schema": "mahoraga.evolution_governor", "schema_version": 1,
            "governor_version": self.VERSION, "policy": asdict(self.policy),
            "candidates": records, "automatic_execution": False,
            "automatic_promotion": False, "external_effects_allowed": False,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload["snapshot_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return payload
