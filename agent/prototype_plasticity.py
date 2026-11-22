"""Lightweight online prototype learning with bounded per-prototype plasticity.

This learner is modality-agnostic: it consumes finite feature vectors produced by
an upstream encoder. It does not extract image, audio, or language features and
does not claim to be a general language model.

Learning requires an explicit caller approval flag and attached evidence. The
evidence is retained as caller-supplied provenance; it is not independently
authenticated by this component.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from threading import RLock
from typing import Any

import numpy as np


class PrototypePlasticityError(ValueError):
    """Raised when a prototype-learning operation is invalid."""


class PrototypePlasticity:
    VERSION = "0.2.0"
    EVENT_TYPE = "plasticity.prototype.delta"
    CHECKPOINT_EVENT = "plasticity.prototype.checkpoint"

    MAX_FEATURES = 1024
    MAX_PROTOTYPES = 128
    MAX_LABEL_LENGTH = 100
    MAX_SOURCE_LENGTH = 120
    MAX_EVIDENCE_ITEMS = 8
    MAX_EVIDENCE_LENGTH = 500
    # KnowledgeStore.list_events currently caps every query at 1000 rows.
    RESTORE_EVENT_LIMIT = 1000
    CHECKPOINT_SCAN_LIMIT = 100
    CHECKPOINT_INTERVAL = 500

    MIN_PLASTICITY = 0.005
    MAX_PLASTICITY = 0.35
    INITIAL_PLASTICITY = 0.25
    UPDATE_SIMILARITY = 0.78
    NOVELTY_THRESHOLD = 0.70
    MIN_LABEL_MARGIN = 0.04
    SUCCESS_DECAY = 0.90
    CONFLICT_GROWTH = 1.35

    def __init__(self, cognitive):
        self.cognitive = cognitive
        self.store = cognitive.store
        self._state_lock = RLock()
        self._prototypes: dict[str, dict[str, Any]] = {}
        self._updates_since_checkpoint = 0
        self._load_state()

    @staticmethod
    def _canonical_sha256(value: dict[str, Any]) -> str:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _text(value: Any, field: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise PrototypePlasticityError(
                f"{field} deve ser texto não vazio com até {maximum} caracteres."
            )
        return value.strip()

    @classmethod
    def _vector(cls, value: Any) -> np.ndarray:
        try:
            vector = np.asarray(value, dtype=np.float32)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PrototypePlasticityError("Vetor de características inválido.") from exc

        if vector.ndim != 1 or not 1 <= vector.size <= cls.MAX_FEATURES:
            raise PrototypePlasticityError(
                f"O vetor deve ter entre 1 e {cls.MAX_FEATURES} dimensões."
            )
        if not np.all(np.isfinite(vector)):
            raise PrototypePlasticityError("O vetor contém valores não finitos.")

        norm = float(np.linalg.norm(vector.astype(np.float64)))
        if not math.isfinite(norm) or norm <= 1e-12:
            raise PrototypePlasticityError("O vetor não pode ter norma zero.")

        return (vector / norm).astype(np.float32)

    @staticmethod
    def _state_copy(prototype: dict[str, Any]) -> dict[str, Any]:
        return {
            "prototype_id": prototype["prototype_id"],
            "label": prototype["label"],
            "vector": list(prototype["vector"]),
            "plasticity": float(prototype["plasticity"]),
            "goodness": float(prototype["goodness"]),
            "observations": int(prototype["observations"]),
            "correct_updates": int(prototype["correct_updates"]),
            "misclassifications": int(prototype["misclassifications"]),
            "created_at": prototype["created_at"],
            "updated_at": prototype["updated_at"],
        }

    @classmethod
    def _validate_state(cls, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        try:
            prototype_id = cls._text(value.get("prototype_id"), "prototype_id", 64)
            label = cls._text(value.get("label"), "label", cls.MAX_LABEL_LENGTH)
            vector = cls._vector(value.get("vector"))
            plasticity = float(value.get("plasticity"))
            goodness = float(value.get("goodness"))
            observations = value.get("observations")
            correct_updates = value.get("correct_updates")
            misclassifications = value.get("misclassifications")
            created_at = cls._text(value.get("created_at"), "created_at", 80)
            updated_at = cls._text(value.get("updated_at"), "updated_at", 80)
        except (TypeError, ValueError, OverflowError, PrototypePlasticityError):
            return None

        counters = (observations, correct_updates, misclassifications)
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in counters
        ):
            return None
        if not math.isfinite(plasticity) or not (
            cls.MIN_PLASTICITY <= plasticity <= cls.MAX_PLASTICITY
        ):
            return None
        if not math.isfinite(goodness) or not 0.0 <= goodness <= 1.0:
            return None

        return {
            "prototype_id": prototype_id,
            "label": label,
            "vector": vector.tolist(),
            "plasticity": plasticity,
            "goodness": goodness,
            "observations": observations,
            "correct_updates": correct_updates,
            "misclassifications": misclassifications,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def _load_state(self) -> None:
        """Restore only deltas carrying a verifier-authenticated evidence receipt.

        Legacy checkpoints and deltas remain in SQLite but are quarantined:
        their caller-supplied labels cannot establish trusted provenance.
        Until a signed checkpoint format exists, a full replay window fails
        closed rather than silently restoring a partial model.
        """
        verifier = getattr(self.cognitive, "evidence_verifier", None)
        verify_receipt = getattr(verifier, "verify_receipt", None)
        deltas = self.store.list_events(
            limit=self.RESTORE_EVENT_LIMIT, event_type=self.EVENT_TYPE
        )
        if len(deltas) >= self.RESTORE_EVENT_LIMIT:
            raise PrototypePlasticityError(
                "Histórico de plasticidade atingiu o limite sem checkpoint "
                "criptograficamente verificável; restauração recusada."
            )
        if not callable(verify_receipt):
            self._prototypes = {}
            self._updates_since_checkpoint = 0
            return

        restored = 0
        for event in reversed(deltas):
            payload = event.get("payload", {})
            if (
                not isinstance(payload, dict)
                or payload.get("version") != self.VERSION
                or not isinstance(payload.get("prototypes"), list)
            ):
                continue
            verification_subject = {
                "version": payload.get("version"),
                "operation": payload.get("operation"),
                "prototypes": payload.get("prototypes"),
                "source": payload.get("source"),
                "evidence": payload.get("evidence"),
            }
            try:
                subject_sha256 = self._canonical_sha256(verification_subject)
                if payload.get("verification_subject_sha256") != subject_sha256:
                    continue
                receipt = payload.get("evidence_verification")
                if verify_receipt(
                    receipt=receipt,
                    action="prototype.learn_one",
                    subject_sha256=subject_sha256,
                ) is not True:
                    continue
            except Exception:
                continue

            valid_states = []
            for raw in payload["prototypes"][: self.MAX_PROTOTYPES]:
                state = self._validate_state(raw)
                if state is not None:
                    valid_states.append(state)
            for state in valid_states:
                self._prototypes[state["prototype_id"]] = state
            if valid_states:
                restored += 1

        self._updates_since_checkpoint = restored
        if len(self._prototypes) > self.MAX_PROTOTYPES:
            ordered = sorted(
                self._prototypes.values(),
                key=lambda item: item["updated_at"],
                reverse=True,
            )
            self._prototypes = {
                item["prototype_id"]: item
                for item in ordered[: self.MAX_PROTOTYPES]
            }

    def _persist_changes(
        self,
        prototypes: list[dict[str, Any]],
        operation: str,
        source: str,
        evidence: list[str],
        evidence_verification: dict[str, Any],
        verification_subject_sha256: str,
    ) -> int:
        """Persist a verifier-attested delta before applying in-memory changes."""
        if not prototypes:
            raise PrototypePlasticityError("Nenhuma alteração de protótipo foi fornecida.")

        snapshots = [self._state_copy(item) for item in prototypes]
        verification_subject = {
            "version": self.VERSION,
            "operation": operation,
            "prototypes": snapshots,
            "source": source,
            "evidence": list(evidence),
        }
        actual_digest = self._canonical_sha256(verification_subject)
        if actual_digest != verification_subject_sha256:
            raise PrototypePlasticityError(
                "O conteúdo da alteração mudou depois da verificação da evidência."
            )
        if (
            not isinstance(evidence_verification, dict)
            or evidence_verification.get("verified") is not True
            or evidence_verification.get("subject_sha256") != actual_digest
            or not isinstance(evidence_verification.get("verifier_id"), str)
            or not evidence_verification["verifier_id"].strip()
            or not isinstance(evidence_verification.get("receipt_id"), str)
            or not evidence_verification["receipt_id"].strip()
        ):
            raise PrototypePlasticityError(
                "Recibo de evidência independente inválido."
            )
        payload = {
            **verification_subject,
            "verification_subject_sha256": actual_digest,
            "evidence_verification": dict(evidence_verification),
            "evidence_state": "independently_verified",
        }
        event_id = self.store.record_event(self.EVENT_TYPE, payload)

        # Apply in-memory state only after the durable event was written.
        for item in prototypes:
            self._prototypes[item["prototype_id"]] = item
        self._updates_since_checkpoint += 1
        # Unsigned checkpoints are intentionally disabled. Replay is bounded
        # and authenticated deltas remain the only restoration authority.
        return event_id

    def _checkpoint(self) -> None:
        states = [
            self._state_copy(item)
            for item in sorted(
                self._prototypes.values(),
                key=lambda entry: entry["prototype_id"],
            )
        ]
        self.store.record_event(
            self.CHECKPOINT_EVENT,
            {
                "version": self.VERSION,
                "prototype_count": len(states),
                "prototypes": states,
                "checkpoint_state": "append_only_compaction_snapshot",
            },
        )
        self._updates_since_checkpoint = 0

    def _rank(self, vector: np.ndarray) -> list[tuple[float, dict[str, Any]]]:
        ranked = []
        for prototype in self._prototypes.values():
            center = np.asarray(prototype["vector"], dtype=np.float32)
            if center.shape != vector.shape:
                continue
            similarity = float(np.dot(center, vector))
            if math.isfinite(similarity):
                ranked.append((similarity, prototype))
        ranked.sort(key=lambda item: (-item[0], item[1]["prototype_id"]))
        return ranked

    def _predict(self, vector: np.ndarray) -> dict[str, Any]:
        if not self._prototypes:
            return {
                "recognized": False,
                "decision": "abstain",
                "label": None,
                "reason": "no_prototypes",
                "prototype_id": None,
                "similarity": None,
                "confidence": 0.0,
                "margin": 0.0,
            }

        ranked = self._rank(vector)
        if not ranked:
            return {
                "recognized": False,
                "decision": "abstain",
                "label": None,
                "reason": "feature_dimension_mismatch",
                "prototype_id": None,
                "similarity": None,
                "confidence": 0.0,
                "margin": 0.0,
            }

        best_similarity, best = ranked[0]
        second_label_similarity = next(
            (score for score, item in ranked[1:] if item["label"] != best["label"]),
            -1.0,
        )
        margin = best_similarity - second_label_similarity
        confidence = max(0.0, min(1.0, (best_similarity + 1.0) / 2.0))
        labels = {item["label"] for item in self._prototypes.values()}

        if best_similarity < self.NOVELTY_THRESHOLD:
            decision, reason, recognized, label = (
                "novel", "similarity_below_novelty_threshold", False, None
            )
        elif len(labels) > 1 and margin < self.MIN_LABEL_MARGIN:
            decision, reason, recognized, label = (
                "abstain", "ambiguous_prototype_margin", False, None
            )
        else:
            decision, reason, recognized, label = (
                "recognize", "prototype_match", True, best["label"]
            )

        return {
            "recognized": recognized,
            "decision": decision,
            "label": label,
            "reason": reason,
            "prototype_id": best["prototype_id"],
            "similarity": best_similarity,
            "confidence": confidence,
            "margin": margin,
        }

    def predict(self, features: Any) -> dict[str, Any]:
        """Return one prediction while holding a consistent prototype snapshot."""
        with self._state_lock:
            return self._predict_locked(features)

    def _predict_locked(self, features: Any) -> dict[str, Any]:
        self.cognitive._authorize("local_compute")
        vector = self._vector(features)
        if self._prototypes:
            dimensions = {
                len(item["vector"]) for item in self._prototypes.values()
            }
            if dimensions != {vector.size}:
                raise PrototypePlasticityError(
                    "A dimensão do vetor não corresponde ao modelo existente."
                )
        result = self._predict(vector)
        result.update({
            "component": "PrototypePlasticity",
            "version": self.VERSION,
            "prototype_count": len(self._prototypes),
            "state_modified": False,
            "learning_performed": False,
            "confidence_calibrated": False,
        })
        return result

    def _new_prototype(self, vector: np.ndarray, label: str) -> dict[str, Any]:
        now = self._now()
        return {
            "prototype_id": uuid.uuid4().hex,
            "label": label,
            "vector": vector.tolist(),
            "plasticity": self.INITIAL_PLASTICITY,
            "goodness": 0.5,
            "observations": 1,
            "correct_updates": 0,
            "misclassifications": 0,
            "created_at": now,
            "updated_at": now,
        }

    def learn_one(
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
        """Serialize learning against this shared learner instance."""
        with self._state_lock:
            return self._learn_one_locked(
                features,
                label,
                approved=approved,
                evidence=evidence,
                source=source,
                approval_attestation=approval_attestation,
                evidence_attestation=evidence_attestation,
            )

    def _learn_one_locked(
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
        """Promote one labelled sample only after trusted one-shot authorization.

        The legacy boolean is retained for API compatibility but is never an
        authorization credential. Both verifier providers must be configured.
        """
        if not isinstance(approved, bool):
            raise PrototypePlasticityError("approved deve ser booleano.")
        if not approved:
            raise PermissionError("Aprendizagem exige aprovação explícita.")
        self.cognitive._authorize("record_learning")

        label = self._text(label, "label", self.MAX_LABEL_LENGTH)
        source = self._text(source, "source", self.MAX_SOURCE_LENGTH)
        if evidence is None:
            evidence = []
        if (
            not isinstance(evidence, list)
            or not evidence
            or len(evidence) > self.MAX_EVIDENCE_ITEMS
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > self.MAX_EVIDENCE_LENGTH
                for item in evidence
            )
        ):
            raise PrototypePlasticityError(
                "evidence deve conter de 1 a 8 referências/textos não vazios."
            )
        evidence = [item.strip() for item in evidence]

        vector = self._vector(features)
        if self._prototypes:
            dimensions = {
                len(item["vector"]) for item in self._prototypes.values()
            }
            if dimensions != {vector.size}:
                raise PrototypePlasticityError(
                    "A dimensão do vetor não corresponde ao modelo existente."
                )

        ranked = self._rank(vector)
        nearest = ranked[0] if ranked else None
        same_label = [
            (score, item)
            for score, item in ranked
            if item["label"] == label
        ]
        same_label.sort(key=lambda item: -item[0])

        will_reinforce = bool(
            same_label and same_label[0][0] >= self.UPDATE_SIMILARITY
        )
        if not will_reinforce and len(self._prototypes) >= self.MAX_PROTOTYPES:
            raise PrototypePlasticityError(
                "Limite de protótipos atingido; revisão/pruning exige avaliação separada."
            )

        changes: dict[str, dict[str, Any]] = {}
        conflict = False
        if nearest is not None and nearest[1]["label"] != label:
            similarity, wrong = nearest
            if similarity >= self.UPDATE_SIMILARITY:
                updated_wrong = dict(wrong)
                updated_wrong["misclassifications"] += 1
                updated_wrong["plasticity"] = min(
                    self.MAX_PLASTICITY,
                    updated_wrong["plasticity"] * self.CONFLICT_GROWTH,
                )
                updated_wrong["updated_at"] = self._now()
                changes[updated_wrong["prototype_id"]] = updated_wrong
                conflict = True

        if will_reinforce:
            _, current = same_label[0]
            updated = dict(current)
            alpha = float(updated["plasticity"])
            old_vector = np.asarray(updated["vector"], dtype=np.float32)
            merged = (1.0 - alpha) * old_vector + alpha * vector
            updated["vector"] = self._vector(merged).tolist()
            updated["observations"] += 1
            updated["correct_updates"] += 1
            updated["goodness"] = min(1.0, updated["goodness"] + 0.05)
            updated["plasticity"] = max(
                self.MIN_PLASTICITY, alpha * self.SUCCESS_DECAY
            )
            updated["updated_at"] = self._now()
            operation = "prototype_reinforced"
        else:
            updated = self._new_prototype(vector, label)
            operation = "prototype_created"

        changes[updated["prototype_id"]] = updated
        verification_subject = {
            "version": self.VERSION,
            "operation": operation,
            "prototypes": [
                self._state_copy(item) for item in changes.values()
            ],
            "source": source,
            "evidence": list(evidence),
        }
        subject_sha256 = self._canonical_sha256(verification_subject)
        evidence_verifier = getattr(self.cognitive, "evidence_verifier", None)
        verify_evidence = getattr(evidence_verifier, "verify_attestation", None)
        if evidence_attestation is None or not callable(verify_evidence):
            raise PermissionError(
                "Plasticidade bloqueada: verificador independente de evidências ausente."
            )
        try:
            evidence_receipt = verify_evidence(
                attestation=evidence_attestation,
                action="prototype.learn_one",
                subject_sha256=subject_sha256,
                source=source,
            )
        except Exception as exc:
            raise PermissionError("Evidência não pôde ser verificada.") from exc
        if (
            not isinstance(evidence_receipt, dict)
            or evidence_receipt.get("verified") is not True
            or evidence_receipt.get("subject_sha256") != subject_sha256
            or evidence_receipt.get("source_identity_verified") is not True
            or not isinstance(evidence_receipt.get("source_id"), str)
            or not evidence_receipt["source_id"].strip()
            or not isinstance(evidence_receipt.get("verifier_id"), str)
            or not evidence_receipt["verifier_id"].strip()
            or not isinstance(evidence_receipt.get("receipt_id"), str)
            or not evidence_receipt["receipt_id"].strip()
        ):
            raise PermissionError("A evidência não possui recibo independente válido.")

        approval_verifier = getattr(self.cognitive, "approval_verifier", None)
        consume_approval = getattr(approval_verifier, "consume_attestation", None)
        if approval_attestation is None or not callable(consume_approval):
            raise PermissionError(
                "Plasticidade bloqueada: atestador de aprovação one-shot ausente."
            )
        try:
            approval_consumed = consume_approval(
                attestation=approval_attestation,
                action="prototype.learn_one",
                subject_sha256=subject_sha256,
            )
        except Exception as exc:
            raise PermissionError("A aprovação não pôde ser verificada.") from exc
        if approval_consumed is not True:
            raise PermissionError("Aprovação inválida, expirada ou já utilizada.")

        event_id = self._persist_changes(
            list(changes.values()),
            operation,
            source,
            evidence,
            evidence_receipt,
            subject_sha256,
        )
        return {
            "status": "learned",
            "operation": operation,
            "event_id": event_id,
            "prototype_id": updated["prototype_id"],
            "label": label,
            "conflict_detected": conflict,
            "plasticity": updated["plasticity"],
            "goodness": updated["goodness"],
            "evidence_state": "independently_verified",
            "prototype_count": len(self._prototypes),
            "prototype_parameters_updated": True,
            "general_language_model_weights_updated": False,
            "external_tools_executed": False,
        }

    def state_dict(self) -> dict[str, Any]:
        """Return a stable state snapshot without racing a concurrent update."""
        with self._state_lock:
            return self._state_dict_locked()

    def _state_dict_locked(self) -> dict[str, Any]:
        self.cognitive._authorize("introspect")
        prototypes = [
            self._state_copy(item)
            for item in sorted(
                self._prototypes.values(),
                key=lambda entry: entry["prototype_id"],
            )
        ]
        canonical = json.dumps(
            prototypes, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return {
            "schema": "mahoraga.prototype_plasticity",
            "version": self.VERSION,
            "prototype_count": len(prototypes),
            "feature_dimensions": sorted({
                len(item["vector"]) for item in prototypes
            }),
            "sha256": hashlib.sha256(canonical).hexdigest(),
            "prototypes": prototypes,
        }

    def status(self) -> dict[str, Any]:
        """Return a consistent status snapshot for the shared learner."""
        with self._state_lock:
            return self._status_locked()

    def _status_locked(self) -> dict[str, Any]:
        prototypes = list(self._prototypes.values())
        labels = sorted({item["label"] for item in prototypes})
        mean_plasticity = (
            sum(item["plasticity"] for item in prototypes) / len(prototypes)
            if prototypes else 0.0
        )
        return {
            "component": "PrototypePlasticity",
            "version": self.VERSION,
            "prototype_count": len(prototypes),
            "label_count": len(labels),
            "labels": labels,
            "mean_plasticity": round(mean_plasticity, 6),
            "max_prototypes": self.MAX_PROTOTYPES,
            "max_features": self.MAX_FEATURES,
            "learning_requires_approval": True,
            "approval_verifier_available": callable(
                getattr(getattr(self.cognitive, "approval_verifier", None), "consume_attestation", None)
            ),
            "evidence_verifier_available": callable(
                getattr(getattr(self.cognitive, "evidence_verifier", None), "verify_receipt", None)
            ),
            "legacy_unverified_events_quarantined": True,
            "checkpoint_restore": "disabled_until_signed_checkpoint_format",
            "automatic_checkpoint_compaction": False,
            "evidence_independently_verified": bool(self._prototypes),
            "general_language_model_weights_updated": False,
        }
