import pytest

from agent.adaptive_learning import AdaptiveLearning
from agent.store import KnowledgeStore


class _Verifier:
    def __init__(self, receipt):
        self.receipt = receipt

    def verify_attestation(self, *, attestation, action, subject_sha256, source):
        return {**self.receipt, "subject_sha256": subject_sha256}

    def verify_receipt(self, *, receipt, action, subject_sha256):
        return (
            receipt.get("verified") is True
            and receipt.get("subject_sha256") == subject_sha256
            and receipt.get("signature") == "signature-v1"
        )


class _Cognitive:
    def __init__(self, store, verifier):
        self.store = store
        self.evidence_verifier = verifier

    def _authorize(self, action):
        return None


def _record(tmp_path, receipt):
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = KnowledgeStore(tmp_path / "adaptive-evidence-receipt.sqlite3")
    learning = AdaptiveLearning(_Cognitive(store, _Verifier(receipt)))
    result = learning.record_experience(
        "test evidence receipt boundary",
        "inspect",
        "completed",
        "unit-test",
        validated=True,
        validation_evidence=["unit-test-report"],
        evidence_attestation={"nonce": "receipt-boundary"},
    )
    event = store.list_events(limit=1, event_type=learning.EVENT_TYPE)[0]
    return result, event["payload"], learning


def test_evidence_receipt_preserves_verifier_signature_as_bounded_json(tmp_path):
    receipt = {
        "verified": True,
        "source_identity_verified": True,
        "source_id": "independent-source",
        "verifier_id": "trusted-verifier",
        "receipt_id": "receipt-001",
        "signature": "signature-v1",
    }

    _, episode, learning = _record(tmp_path, receipt)

    assert episode["evidence_verification"]["signature"] == "signature-v1"
    assert episode["evidence_verification"]["source_id"] == "independent-source"
    assert learning._episode_is_independently_verified(episode) is True


@pytest.mark.parametrize(
    "field",
    ["source_id", "verifier_id", "receipt_id"],
)
def test_evidence_receipt_rejects_oversized_identity_fields(tmp_path, field):
    receipt = {
        "verified": True,
        "source_identity_verified": True,
        "source_id": "independent-source",
        "verifier_id": "trusted-verifier",
        "receipt_id": "receipt-001",
        "signature": "signature-v1",
    }
    receipt[field] = "x" * 257

    _, episode, _ = _record(tmp_path, receipt)

    assert episode["evidence_verification"] is None
    assert episode["validation_state"] == "caller_asserted_unverified"


def test_evidence_receipt_rejects_oversized_or_non_json_envelopes(tmp_path):
    oversized = {
        "verified": True,
        "source_identity_verified": True,
        "source_id": "independent-source",
        "verifier_id": "trusted-verifier",
        "receipt_id": "receipt-001",
        "signature": "x" * 9000,
    }
    _, oversized_episode, _ = _record(tmp_path / "oversized", oversized)
    assert oversized_episode["evidence_verification"] is None

    non_json = {
        "verified": True,
        "source_identity_verified": True,
        "source_id": "independent-source",
        "verifier_id": "trusted-verifier",
        "receipt_id": "receipt-001",
        "signature": "signature-v1",
        "opaque_object": object(),
    }
    _, non_json_episode, _ = _record(tmp_path / "non-json", non_json)
    assert non_json_episode["evidence_verification"] is None
