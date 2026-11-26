from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.identity_engine import IdentityEngine
from agent.store import KnowledgeStore


def _identity_profile(root):
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema": "mahoraga.identity_profile",
        "version": "1.0.0",
        "identity": {"name": "Mahoraga", "designation": "agente", "purpose": "evoluir"},
        "core_principles": ["integridade"],
        "personality": {
            "traits": ["metódico"],
            "behavioral_expression": "operacional",
            "invariants": ["não inventar"],
        },
        "communication": {"behavior": ["clareza"]},
        "autonomy": {"default_mode": "offline_first", "policy": "governada"},
        "self_image": {"concept": "self-model persistente"},
        "continuity": {"strategy": "KnowledgeStore"},
        "creative_domains": [],
        "goals": [],
        "boundaries": ["sem alegações subjetivas"],
    }
    (config / "identity_profile.json").write_text(
        json.dumps(profile), encoding="utf-8"
    )


class AllowDharma:
    def evaluate(self, action):
        return SimpleNamespace(allowed=True, reason="allowed")


class ApprovalVerifier:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    def consume_attestation(self, *, attestation, action, subject_sha256):
        self.calls.append((attestation, action, subject_sha256))
        return self.accepted


class EvidenceVerifier:
    def __init__(self, *, valid=True, oversized=False):
        self.valid = valid
        self.oversized = oversized
        self.calls = []

    def verify_attestation(self, *, attestation, action, subject_sha256, source):
        self.calls.append((attestation, action, subject_sha256, source))
        return {
            "verified": self.valid,
            "subject_sha256": subject_sha256 if self.valid else "0" * 64,
            "source_identity_verified": self.valid,
            "source_id": "s" * (257 if self.oversized else 20),
            "verifier_id": "unit-test-verifier",
            "receipt_id": "receipt-identity-001",
        }


def _build(root, *, approved=True, evidence=True, receipt_valid=True, approval_valid=True, oversized=False):
    _identity_profile(root)
    store = KnowledgeStore(root / "identity.sqlite3")
    approval = ApprovalVerifier(approval_valid) if approved else None
    evidence_provider = EvidenceVerifier(valid=receipt_valid, oversized=oversized) if evidence else None
    identity = IdentityEngine(
        root,
        store,
        AllowDharma(),
        approval_verifier=approval,
        evidence_verifier=evidence_provider,
    )
    return identity, store, approval, evidence_provider


def _record(identity, **overrides):
    values = {
        "title": "Marco validado",
        "description": "Capacidade demonstrada por evidência independente",
        "evidence": ["ci:run-123", "commit:abc123"],
        "approved": True,
        "source": "human_feedback",
        "approval_attestation": {"opaque": "approval-token"},
        "evidence_attestation": {"opaque": "evidence-token"},
    }
    values.update(overrides)
    return identity.record_milestone(**values)


def test_milestone_requires_verifier_providers_not_boolean_claim(tmp_path):
    identity, store, _, _ = _build(tmp_path, approved=False, evidence=False)
    with pytest.raises(PermissionError, match="verificador independente"):
        _record(identity)
    assert store.list_events(event_type="identity.milestone.recorded") == []


def test_milestone_verifies_exact_subject_before_consuming_approval(tmp_path):
    identity, store, approval, evidence = _build(tmp_path)
    result = _record(identity)
    assert result["status"] == "recorded"
    assert result["approval_verified"] is True
    assert result["evidence_verified"] is True
    assert approval.calls[0][1] == "identity.record_milestone"
    assert evidence.calls[0][1] == "identity.record_milestone"
    assert approval.calls[0][2] == evidence.calls[0][2] == result["subject_sha256"]
    payload = store.list_events(event_type="identity.milestone.recorded")[0]["payload"]
    assert payload["approval_verified"] is True
    assert payload["evidence_receipt"]["receipt_id"] == "receipt-identity-001"
    assert "approval_attestation" not in payload
    assert "evidence_attestation" not in payload


def test_invalid_evidence_does_not_consume_approval_or_write_event(tmp_path):
    identity, store, approval, _ = _build(tmp_path, receipt_valid=False)
    with pytest.raises(PermissionError, match="recibo independente"):
        _record(identity)
    assert approval.calls == []
    assert store.list_events(event_type="identity.milestone.recorded") == []


def test_rejected_or_reused_approval_does_not_write_event(tmp_path):
    identity, store, approval, _ = _build(tmp_path, approval_valid=False)
    with pytest.raises(PermissionError, match="inválida, expirada ou já utilizada"):
        _record(identity)
    assert len(approval.calls) == 1
    assert store.list_events(event_type="identity.milestone.recorded") == []


def test_receipt_metadata_is_bounded_and_duplicate_evidence_is_rejected(tmp_path):
    identity, store, approval, _ = _build(tmp_path, oversized=True)
    with pytest.raises(PermissionError, match="recibo independente"):
        _record(identity)
    assert approval.calls == []
    with pytest.raises(ValueError, match="duplicadas"):
        _record(identity, evidence=["ci:run-123", "ci:run-123"])
    assert store.list_events(event_type="identity.milestone.recorded") == []


def test_caller_boolean_without_attestations_never_records_milestone(tmp_path):
    identity, store, _, _ = _build(tmp_path)
    with pytest.raises(PermissionError):
        identity.record_milestone(
            "Marco", "Teste", ["ci:123"], approved=True
        )
    assert store.list_events(event_type="identity.milestone.recorded") == []
