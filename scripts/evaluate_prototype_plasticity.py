"""Reproducible synthetic evaluation for PrototypePlasticity.

This benchmark measures adaptation, retention, abstention and novelty handling
on a small, deterministic feature-space fixture. It is not a language, vision or
audio benchmark and does not establish real-world generalization.
Run from the repository root with:
    python -m scripts.evaluate_prototype_plasticity
"""
from __future__ import annotations

import copy
import json
import sys
import uuid
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.prototype_plasticity import PrototypePlasticity


DATASET_VERSION = "prototype-plasticity-synthetic-v1"


class EvaluationStore:
    """Ephemeral append-only store; no production database is opened."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record_event(self, event_type: str, payload: dict[str, Any]) -> int:
        event_id = len(self.events) + 1
        self.events.append({
            "id": event_id,
            "event_type": event_type,
            "payload": copy.deepcopy(payload),
        })
        return event_id

    def list_events(
        self, limit: int = 100, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        selected = [
            item for item in self.events
            if event_type is None or item["event_type"] == event_type
        ]
        return copy.deepcopy(list(reversed(selected[-limit:])))


class SyntheticEvidenceVerifier:
    """Non-production verifier double; valid only inside this synthetic benchmark."""

    def verify_attestation(self, *, attestation, action, subject_sha256, source):
        if (
            not isinstance(attestation, dict)
            or not isinstance(attestation.get("nonce"), str)
            or not attestation["nonce"]
            or action != "prototype.learn_one"
            or source != "isolated_synthetic_benchmark"
        ):
            return None
        return {
            "verified": True,
            "verifier_id": "synthetic-benchmark-evidence-verifier",
            "receipt_id": attestation["nonce"],
            "subject_sha256": subject_sha256,
            "source_identity_verified": True,
            "source_id": source,
        }

    def verify_receipt(self, *, receipt, action, subject_sha256):
        return (
            isinstance(receipt, dict)
            and receipt.get("verified") is True
            and receipt.get("verifier_id") == "synthetic-benchmark-evidence-verifier"
            and receipt.get("subject_sha256") == subject_sha256
            and receipt.get("source_identity_verified") is True
            and isinstance(receipt.get("source_id"), str)
            and bool(receipt["source_id"].strip())
            and isinstance(receipt.get("receipt_id"), str)
            and bool(receipt["receipt_id"].strip())
            and action == "prototype.learn_one"
        )


class SyntheticApprovalVerifier:
    """One-shot synthetic approval double; never used by the production runtime."""

    def __init__(self) -> None:
        self.used_nonces: set[str] = set()

    def consume_attestation(self, *, attestation, action, subject_sha256):
        if (
            not isinstance(attestation, dict)
            or attestation.get("approved") is not True
            or action != "prototype.learn_one"
            or not isinstance(subject_sha256, str)
            or len(subject_sha256) != 64
        ):
            return False
        nonce = attestation.get("nonce")
        if not isinstance(nonce, str) or not nonce or nonce in self.used_nonces:
            return False
        self.used_nonces.add(nonce)
        return True


class EvaluationCognitive:
    """Synthetic trust providers confined to this disposable benchmark."""

    ALLOWED = {"local_compute", "record_learning", "introspect"}

    def __init__(self, store: EvaluationStore) -> None:
        self.store = store
        self.evidence_verifier = SyntheticEvidenceVerifier()
        self.approval_verifier = SyntheticApprovalVerifier()

    def _authorize(self, action: str) -> bool:
        if action not in self.ALLOWED:
            raise PermissionError(f"benchmark action not allowed: {action}")
        return True


def _learn(
    learner: PrototypePlasticity,
    vector: list[float],
    label: str,
    sample_id: str,
) -> None:
    learner.learn_one(
        vector,
        label,
        approved=True,
        evidence=[f"synthetic-fixture:{DATASET_VERSION}:{sample_id}"],
        source="isolated_synthetic_benchmark",
        approval_attestation={
            "approved": True,
            "nonce": uuid.uuid4().hex,
        },
        evidence_attestation={
            "nonce": uuid.uuid4().hex,
        },
    )


def _evaluate(
    learner: PrototypePlasticity,
    cases: list[tuple[list[float], str]],
) -> dict[str, Any]:
    total = len(cases)
    if total == 0:
        raise ValueError("evaluation cases cannot be empty")

    predictions = [learner.predict(vector) for vector, _ in cases]
    recognized = [
        item for item in predictions if item.get("decision") == "recognize"
    ]
    correct = sum(
        item.get("decision") == "recognize" and item.get("label") == expected
        for item, (_, expected) in zip(predictions, cases)
    )
    novel = sum(item.get("decision") == "novel" for item in predictions)
    abstained = sum(item.get("decision") == "abstain" for item in predictions)
    return {
        "cases": total,
        "correct": correct,
        "accuracy": round(correct / total, 4),
        "coverage": round(len(recognized) / total, 4),
        "selective_accuracy": round(correct / len(recognized), 4)
        if recognized else 0.0,
        "abstentions": abstained,
        "novel_decisions": novel,
    }


def run_benchmark() -> dict[str, Any]:
    """Run the full evaluation against a disposable in-memory store."""
    store = EvaluationStore()
    cognitive = EvaluationCognitive(store)
    learner = PrototypePlasticity(cognitive)

    old_support = [
        ([1.0, 0.0, 0.0, 0.0], "leaf", "leaf-01"),
        ([0.995, 0.1, 0.0, 0.0], "leaf", "leaf-02"),
        ([0.995, -0.1, 0.0, 0.0], "leaf", "leaf-03"),
        ([0.0, 1.0, 0.0, 0.0], "stone", "stone-01"),
        ([0.1, 0.995, 0.0, 0.0], "stone", "stone-02"),
        ([-0.1, 0.995, 0.0, 0.0], "stone", "stone-03"),
    ]
    old_holdout = [
        ([0.99, 0.12, 0.0, 0.0], "leaf"),
        ([0.99, -0.12, 0.0, 0.0], "leaf"),
        ([0.12, 0.99, 0.0, 0.0], "stone"),
        ([-0.12, 0.99, 0.0, 0.0], "stone"),
    ]
    new_holdout = [
        ([0.7071, 0.7071, 0.0, 0.0], "flower"),
        ([0.705, 0.71, 0.0, 0.0], "flower"),
    ]
    novel_holdout = [
        ([0.0, 0.0, 0.0, 1.0], "unknown"),
    ]

    for vector, label, sample_id in old_support:
        _learn(learner, vector, label, sample_id)

    old_before = _evaluate(learner, old_holdout)
    new_before = _evaluate(learner, new_holdout)
    ambiguous_before = learner.predict([0.7071, 0.7071, 0.0, 0.0])

    new_support = [
        ([0.79, 0.62, 0.0, 0.0], "flower", "flower-01"),
        ([0.71, 0.70, 0.0, 0.0], "flower", "flower-02"),
        ([0.63, 0.78, 0.0, 0.0], "flower", "flower-03"),
    ]
    for vector, label, sample_id in new_support:
        _learn(learner, vector, label, sample_id)

    old_after = _evaluate(learner, old_holdout)
    new_after = _evaluate(learner, new_holdout)
    novel_after = _evaluate(learner, novel_holdout)

    # Reconstruct from the same disposable append-only log to test replay.
    restored = PrototypePlasticity(EvaluationCognitive(store))
    restored_old = _evaluate(restored, old_holdout)
    restored_new = _evaluate(restored, new_holdout)
    restored_novel = _evaluate(restored, novel_holdout)

    retention_loss = round(
        max(0.0, old_before["accuracy"] - old_after["accuracy"]), 4
    )
    adaptation_gain = round(
        new_after["accuracy"] - new_before["accuracy"], 4
    )
    ambiguous_abstained = ambiguous_before.get("decision") == "abstain"
    ood_rejected = novel_after["novel_decisions"] == novel_after["cases"]

    gates = {
        "baseline_old_classes_recognized": old_before["accuracy"] == 1.0,
        "new_class_learned": new_after["accuracy"] == 1.0,
        "old_class_retention": retention_loss == 0.0,
        "new_class_adaptation_improved": adaptation_gain > 0.0,
        "ambiguous_input_abstained_before_learning": ambiguous_abstained,
        "out_of_distribution_input_rejected": ood_rejected,
        "replay_preserved_old_classes": restored_old["accuracy"] == old_after["accuracy"],
        "replay_preserved_new_class": restored_new["accuracy"] == new_after["accuracy"],
        "replay_preserved_novelty_decision": (
            restored_novel["novel_decisions"] == novel_after["novel_decisions"]
        ),
    }

    return {
        "schema": "mahoraga.prototype_plasticity_evaluation",
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "algorithm_version": PrototypePlasticity.VERSION,
        "evaluation_scope": "synthetic_feature_vectors_only",
        "persistence_scope": "disposable_in_memory_append_only_store",
        "metrics": {
            "old_classes_before_adaptation": old_before,
            "new_class_before_adaptation": new_before,
            "old_classes_after_adaptation": old_after,
            "new_class_after_adaptation": new_after,
            "novel_class_after_adaptation": novel_after,
            "ambiguous_before_adaptation": {
                "decision": ambiguous_before.get("decision"),
                "reason": ambiguous_before.get("reason"),
                "abstained": ambiguous_abstained,
            },
            "retention_loss": retention_loss,
            "new_class_accuracy_gain": adaptation_gain,
            "replay": {
                "old_classes_accuracy": restored_old["accuracy"],
                "new_class_accuracy": restored_new["accuracy"],
                "novel_class_rejections": restored_novel["novel_decisions"],
            },
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "limitations": [
            "Synthetic vectors do not measure language, vision or audio understanding.",
            "Synthetic trust-provider doubles exercise the production attestation contract but do not authenticate real human approval or external evidence.",
            "The benchmark does not update neural-network weights.",
            "Passing this benchmark does not establish generalization to real data or Android hardware.",
        ],
    }


def main() -> int:
    result = run_benchmark()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
