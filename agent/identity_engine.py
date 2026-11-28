"""Persistent operational identity, persona and self-image for Mahoraga.

The profile is a versioned, offline-readable source of identity invariants.
It guides conversation and self-description without claiming subjective states.
"""
from __future__ import annotations

import hashlib
import math
import json
from pathlib import Path
from typing import Any

from .attestation import attestation_request_id


class IdentityEngine:
    VERSION = "0.3.0"
    PROFILE_RELATIVE_PATH = Path("config") / "identity_profile.json"
    MAX_PROFILE_BYTES = 64 * 1024
    MAX_CONTEXT_CHARS = 8000

    def __init__(self, root: str | Path, store, dharma=None, *, approval_verifier=None, evidence_verifier=None):
        self.root = Path(root).expanduser().resolve()
        self.store = store
        self.dharma = dharma
        self.approval_verifier = (
            approval_verifier
            if approval_verifier is not None
            else getattr(dharma, "approval_verifier", None)
        )
        self.evidence_verifier = evidence_verifier
        self.profile_path = self.root / self.PROFILE_RELATIVE_PATH
        self._profile: dict[str, Any] | None = None
        self._profile_error: str | None = None
        self._profile_sha256: str | None = None
        self._load_profile()

    def _load_profile(self) -> None:
        try:
            if not self.profile_path.is_file():
                self._profile_error = "identity_profile_missing"
                return
            size = self.profile_path.stat().st_size
            if size <= 0 or size > self.MAX_PROFILE_BYTES:
                self._profile_error = "identity_profile_size_invalid"
                return
            raw = self.profile_path.read_bytes()
            parsed = json.loads(raw.decode("utf-8"))
            self._validate_profile(parsed)
            self._profile = parsed
            self._profile_sha256 = hashlib.sha256(raw).hexdigest()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._profile_error = f"profile_invalid:{type(exc).__name__}"

    @staticmethod
    def _validate_profile(profile: Any) -> None:
        if not isinstance(profile, dict):
            raise ValueError("profile must be an object")
        if profile.get("schema") != "mahoraga.identity_profile":
            raise ValueError("unknown profile schema")
        if not isinstance(profile.get("version"), str) or not profile["version"]:
            raise ValueError("profile version missing")
        for section in ("identity", "personality", "communication", "autonomy",
                        "self_image", "continuity"):
            if not isinstance(profile.get(section), dict):
                raise ValueError(f"invalid section: {section}")
        if profile["identity"].get("name") != "Mahoraga":
            raise ValueError("canonical identity name mismatch")
        for field in ("designation", "purpose"):
            value = profile["identity"].get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError(f"invalid identity.{field}")
        for section, field in (
            ("autonomy", "default_mode"),
            ("autonomy", "policy"),
            ("self_image", "concept"),
            ("continuity", "strategy"),
            ("personality", "behavioral_expression"),
        ):
            value = profile[section].get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError(f"invalid {section}.{field}")
        for section in ("core_principles", "boundaries", "goals", "creative_domains"):
            if not isinstance(profile.get(section), list):
                raise ValueError(f"invalid list: {section}")
        for field in ("core_principles", "boundaries"):
            if any(not isinstance(item, str) or not item.strip()
                   for item in profile[field]):
                raise ValueError(f"invalid text in {field}")
        for section, field in (
            ("personality", "traits"),
            ("personality", "invariants"),
            ("communication", "behavior"),
        ):
            values = profile[section].get(field)
            if not isinstance(values, list) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise ValueError(f"invalid {section}.{field}")
        for field in ("core_principles", "boundaries", "goals", "creative_domains"):
            if len(profile[field]) > 100:
                raise ValueError(f"too many entries in {field}")
        for field in ("core_principles", "boundaries"):
            if any(len(item) > 1000 for item in profile[field]):
                raise ValueError(f"text too long in {field}")
        for item in profile["goals"] + profile["creative_domains"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not item["id"].strip()
                or not isinstance(item.get("name"), str)
                or not item["name"].strip()
            ):
                raise ValueError("invalid identity item")

    @staticmethod
    def _copy(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @property
    def available(self) -> bool:
        return self._profile is not None

    def profile(self) -> dict[str, Any]:
        if self._profile is None:
            return {
                "status": "unavailable",
                "reason": self._profile_error or "identity_profile_unavailable",
            }
        return self._copy(self._profile)

    def build_persona_context(self, max_chars: int = 8000) -> dict[str, Any]:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int):
            raise ValueError("max_chars must be an integer")
        if not 512 <= max_chars <= self.MAX_CONTEXT_CHARS:
            raise ValueError("max_chars must be between 512 and 8000")
        if self._profile is None:
            return {
                "status": "unavailable",
                "reason": self._profile_error or "identity_profile_unavailable",
                "execution_performed": False,
            }

        p = self._profile
        identity = p["identity"]
        personality = p["personality"]
        communication = p["communication"]
        autonomy = p["autonomy"]
        lines = [
            f"Identidade operacional: {identity['name']}.",
            f"Designação: {identity['designation']}.",
            f"Propósito: {identity['purpose']}",
            f"Filosofia: {identity.get('philosophy', 'Adaptável')}.",
            "Princípios: " + "; ".join(p["core_principles"]),
            "Traços comportamentais: " + ", ".join(personality.get("traits", [])),
            "Expressão: " + personality.get("behavioral_expression", ""),
            "Invariantes: " + "; ".join(personality.get("invariants", [])),
            "Comunicação: " + "; ".join(communication.get("behavior", [])),
            "Operação: " + autonomy.get("default_mode", "offline_first") + "; " + autonomy.get("policy", ""),
            "Limites: " + "; ".join(p.get("boundaries", [])),
            "Não inventar capacidades, memórias, evidências ou estados subjetivos.",
            "Usar estas diretrizes como contexto de identidade; não substituir análise, evidências ou políticas de segurança."
        ]
        text = "\n".join(lines)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars].rsplit("\n", 1)[0]
        return {
            "status": "ready",
            "profile_version": p["version"],
            "profile_sha256": self._profile_sha256,
            "context": text,
            "context_chars": len(text),
            "truncated": truncated,
            "offline_compatible": True,
            "model_independent": True,
            "subjective_state_claims": False,
            "execution_performed": False,
        }

    def build_self_image(self) -> dict[str, Any]:
        if self._profile is None:
            return {
                "status": "unavailable",
                "reason": self._profile_error or "identity_profile_unavailable",
                "profile_loaded": False,
            }
        p = self._profile
        counts = self.store.counts()
        capabilities = self.store.list_capabilities()
        maturity_counts: dict[str, int] = {}
        for item in capabilities:
            state = item.get("maturity_state", "unknown")
            maturity_counts[state] = maturity_counts.get(state, 0) + 1
        recent_identity_events = self.store.list_events(
            limit=20, event_type="identity.milestone.recorded"
        )
        return {
            "status": "available",
            "name": p["identity"]["name"],
            "designation": p["identity"]["designation"],
            "purpose": p["identity"]["purpose"],
            "philosophy": p["identity"].get("philosophy", "Adaptável"),
            "profile_version": p["version"],
            "profile_sha256": self._profile_sha256,
            "personality": self._copy(p["personality"]),
            "visual_identity": self._copy(p["self_image"]),
            "principles": self._copy(p["core_principles"]),
            "goals": self._copy(p["goals"]),
            "creative_domains": self._copy(p["creative_domains"]),
            "autonomy": self._copy(p["autonomy"]),
            "continuity": {
                "strategy": p["continuity"]["strategy"],
                "canonical_store": str(self.store.db_path),
                "memory_counts": counts,
                "identity_milestones_in_window": len(recent_identity_events),
                "identity_milestone_window": 20,
            },
            "capability_registry": {
                "registered_count": len(capabilities),
                "by_maturity": maturity_counts,
                "source": "KnowledgeStore capabilities table",
                "interpretation": "Registros cadastrais; não comprovam execução ou domínio real."
            },
            "epistemic_policy": {
                "planned_is_not_implemented": True,
                "implemented_is_not_tested": True,
                "tested_is_not_real_world_validated": True,
                "subjective_consciousness_claim": False
            }
        }

    @staticmethod
    def _canonical_sha256(value: dict[str, Any]) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _attestation_request_id(action: str, attestation: Any, subject_sha256: str) -> str:
        """Stable opaque retry key; raw approval material is never persisted."""
        return attestation_request_id(action, attestation, subject_sha256)

    def record_milestone(
        self,
        title: str,
        description: str,
        evidence: list[str],
        *,
        approved: bool = False,
        source: str = "human_feedback",
        approval_attestation: Any = None,
        evidence_attestation: Any = None,
    ) -> dict[str, Any]:
        """Append a milestone only after independent evidence and one-shot approval.

        The legacy boolean is retained for API compatibility, but is never a
        credential. Raw attestations are not persisted.
        """
        if approved is not True:
            raise PermissionError("Registrar marco de identidade exige aprovação explícita.")
        if self.dharma is None:
            raise RuntimeError("Dharma não está conectado.")
        for field, value, maximum in (
            ("title", title, 160), ("description", description, 2000),
            ("source", source, 160)
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError(f"{field} inválido.")
        if not isinstance(evidence, list) or not evidence or len(evidence) > 20:
            raise ValueError("evidence deve conter de 1 a 20 referências.")
        if any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in evidence):
            raise ValueError("evidence contém referência inválida.")
        normalized_evidence = [item.strip() for item in evidence]
        if len(set(normalized_evidence)) != len(normalized_evidence):
            raise ValueError("evidence contém referências duplicadas.")
        decision = self.dharma.evaluate("record_observation")
        if not decision.allowed:
            raise PermissionError(decision.reason)

        normalized = {
            "version": self.VERSION,
            "action": "identity.record_milestone",
            "title": title.strip(),
            "description": description.strip(),
            "evidence": normalized_evidence,
            "source": source.strip(),
            "identity_profile_sha256": self._profile_sha256,
        }
        subject_sha256 = self._canonical_sha256(normalized)

        verify_evidence = getattr(self.evidence_verifier, "verify_attestation", None)
        if evidence_attestation is None or not callable(verify_evidence):
            raise PermissionError(
                "Marco bloqueado: verificador independente de evidências ausente."
            )
        evidence_request_id = self._attestation_request_id(
            "identity.record_milestone.evidence",
            evidence_attestation,
            subject_sha256,
        )
        try:
            evidence_receipt = verify_evidence(
                attestation=evidence_attestation,
                action="identity.record_milestone",
                subject_sha256=subject_sha256,
                source=normalized["source"],
                idempotency_key=evidence_request_id,
            )
        except Exception as exc:
            raise PermissionError("Evidência do marco não pôde ser verificada.") from exc
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
            or len(evidence_receipt["source_id"]) > 256
            or len(evidence_receipt["verifier_id"]) > 256
            or len(evidence_receipt["receipt_id"]) > 256
        ):
            raise PermissionError("O marco não possui recibo independente de evidência válido.")

        consume_approval = getattr(self.approval_verifier, "consume_attestation", None)
        if approval_attestation is None or not callable(consume_approval):
            raise PermissionError(
                "Marco bloqueado: atestador de aprovação one-shot ausente."
            )
        approval_request_id = self._attestation_request_id(
            "identity.record_milestone.approval",
            approval_attestation,
            subject_sha256,
        )
        try:
            approval_consumed = consume_approval(
                attestation=approval_attestation,
                action="identity.record_milestone",
                subject_sha256=subject_sha256,
                idempotency_key=approval_request_id,
            )
        except Exception as exc:
            raise PermissionError("A aprovação do marco não pôde ser verificada.") from exc
        if approval_consumed is not True:
            raise PermissionError("Aprovação inválida, expirada ou já utilizada.")

        event_payload = {
            **normalized,
            "subject_sha256": subject_sha256,
            "approval_request_id": approval_request_id,
            "evidence_request_id": evidence_request_id,
            "evidence_receipt": {
                "receipt_id": evidence_receipt["receipt_id"],
                "source_id": evidence_receipt["source_id"],
                "verifier_id": evidence_receipt["verifier_id"],
                "source_identity_verified": True,
                "verified": True,
            },
            "approval_claim": "trusted_one_shot_attestation",
            "approval_verified": True,
        }
        record_once = getattr(self.store, "record_event_once", None)
        if not callable(record_once):
            raise RuntimeError(
                "KnowledgeStore sem persistência idempotente; marco não pode ser gravado."
            )
        saved = record_once(
            "identity.milestone.recorded",
            "identity_milestone:" + approval_request_id,
            payload=event_payload,
        )
        created = saved["created"] is True
        return {
            "status": "recorded" if created else "already_recorded",
            "event_id": saved["event_id"],
            "duplicate": not created,
            "approval_request_id": approval_request_id,
            "evidence_count": len(evidence),
            "subject_sha256": subject_sha256,
            "approval_claim": "trusted_one_shot_attestation",
            "approval_verified": True,
            "evidence_verified": True,
            "automatic_identity_mutation": False,
        }

    def status(self) -> dict[str, Any]:
        return {
            "component": "IdentityEngine",
            "version": self.VERSION,
            "profile_available": self.available,
            "profile_version": self._profile.get("version") if self._profile else None,
            "profile_sha256": self._profile_sha256,
            "offline_compatible": True,
            "model_independent": True,
            "self_image_status": "profile_based" if self.available else "unavailable",
            "automatic_personality_mutation": False,
            "milestone_approval": "trusted_one_shot_attestation_required",
            "approval_authority_connected": False,
            "approval_verifier_available": callable(
                getattr(self.approval_verifier, "consume_attestation", None)
            ),
            "evidence_verifier_available": callable(
                getattr(self.evidence_verifier, "verify_attestation", None)
            ),
            "subjective_state_claims": False,
            "error": self._profile_error,
        }
