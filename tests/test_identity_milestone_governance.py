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
        self.consumed = {}

    def consume_attestation(self, *, attestation, action, subject_sha256, idempotency_key):
        self.calls.append((attestation, action, subject_sha256, idempotency_key))
        if idempotency_key in self.consumed:
            previous = self.consumed[idempotency_key]
            return previous == (action, subject_sha256, self.accepted) and self.accepted is True
        self.consumed[idempotency_key] = (action, subject_sha256, self.accepted)
        return self.accepted


class EvidenceVerifier:
    def __init__(self, *, valid=True, oversized=False):
        self.valid = valid
        self.oversized = oversized
        self.calls = []

    def verify_attestation(self, *, attestation, action, subject_sha256, source, idempotency_key):
        self.calls.append((attestation, action, subject_sha256, source, idempotency_key))
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
    assert identity.VERSION == "0.3.0"
    assert result["status"] == "recorded"
    assert result["approval_verified"] is True
    assert result["evidence_verified"] is True
    assert approval.calls[0][1] == "identity.record_milestone"
    assert evidence.calls[0][1] == "identity.record_milestone"
    assert approval.calls[0][2] == evidence.calls[0][2] == result["subject_sha256"]
    assert len(approval.calls[0][3]) == len(evidence.calls[0][4]) == 64
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


def test_rejected_approval_remains_rejected_on_idempotent_replay(tmp_path):
    identity, store, approval, _ = _build(tmp_path, approval_valid=False)
    for _ in range(2):
        with pytest.raises(PermissionError, match="inválida, expirada ou já utilizada"):
            _record(identity)
    assert len(approval.calls) == 2
    assert approval.calls[0][3] == approval.calls[1][3]
    assert store.list_events(event_type="identity.milestone.recorded") == []


def test_receipt_metadata_is_bounded_and_duplicate_evidence_is_rejected(tmp_path):
    identity, store, approval, _ = _build(tmp_path, oversized=True)
    with pytest.raises(PermissionError, match="recibo independente"):
        _record(identity)
    assert approval.calls == []
    with pytest.raises(ValueError, match="duplicadas"):
        _record(identity, evidence=["ci:run-123", "ci:run-123"])
    assert store.list_events(event_type="identity.milestone.recorded") == []


def test_approval_consumption_and_event_append_are_retry_safe(tmp_path):
    identity, store, approval, evidence = _build(tmp_path)
    original_record_once = store.record_event_once
    fail_once = {"enabled": True}

    def fail_first_persist(*args, **kwargs):
        if fail_once["enabled"]:
            fail_once["enabled"] = False
            raise OSError("simulated sqlite write failure")
        return original_record_once(*args, **kwargs)

    store.record_event_once = fail_first_persist
    with pytest.raises(OSError, match="simulated sqlite write failure"):
        _record(identity)

    first_key = approval.calls[0][3]
    assert len(first_key) == 64
    assert store.list_events(event_type="identity.milestone.recorded") == []

    result = _record(identity)
    assert result["status"] == "recorded"
    assert approval.calls[1][3] == first_key
    assert evidence.calls[1][4] == evidence.calls[0][4]

    replay = _record(identity)
    assert replay["status"] == "already_recorded"
    assert replay["event_id"] == result["event_id"]
    assert approval.calls[2][3] == first_key
    assert evidence.calls[2][4] == evidence.calls[0][4]
    assert len(store.list_events(event_type="identity.milestone.recorded")) == 1


def test_approval_request_id_is_bound_to_subject_and_opaque_token():
    from agent.identity_engine import IdentityEngine

    subject = "a" * 64
    first = IdentityEngine._attestation_request_id("identity.record_milestone.approval", {"token": "one"}, subject)
    replay = IdentityEngine._approval_request_id({"token": "one"}, subject)
    changed_token = IdentityEngine._attestation_request_id("identity.record_milestone.approval", {"token": "two"}, subject)
    changed_subject = IdentityEngine._attestation_request_id("identity.record_milestone.approval", {"token": "one"}, "b" * 64)
    assert first == replay
    assert len(first) == 64
    assert first != changed_token
    assert first != changed_subject
    with pytest.raises(PermissionError, match="limite de tamanho"):
        IdentityEngine._attestation_request_id("identity.record_milestone.approval", {"token": "x" * 9000}, subject)


def test_caller_boolean_without_attestations_never_records_milestone(tmp_path):
    identity, store, _, _ = _build(tmp_path)
    with pytest.raises(PermissionError):
        identity.record_milestone(
            "Marco", "Teste", ["ci:123"], approved=True
        )
    assert store.list_events(event_type="identity.milestone.recorded") == []
