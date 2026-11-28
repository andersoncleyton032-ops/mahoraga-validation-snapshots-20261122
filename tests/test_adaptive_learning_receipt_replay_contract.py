from types import SimpleNamespace

import pytest

from agent.adaptive_learning import AdaptiveLearning


class AcceptingVerifier:
    def __init__(self):
        self.calls = []
        self.receipt = None

    def verify_receipt(self, *, receipt, action, subject_sha256):
        self.calls.append((action, subject_sha256))
        self.receipt = receipt
        return True


def build_episode(**receipt_overrides):
    subject = {
        "task": "bounded receipt replay",
        "action": "inspect",
        "outcome": "completed",
        "source": "independent-test-source",
        "validation_state": "validated",
    }
    subject_sha256 = AdaptiveLearning._canonical_sha256(subject)
    receipt = {
        "verified": True,
        "verifier_id": "test-verifier",
        "receipt_id": "receipt-1",
        "subject_sha256": subject_sha256,
        "source_identity_verified": True,
        "source_id": "independent-test-source",
        "signature": {"algorithm": "test", "value": "signature-bytes"},
    }
    receipt.update(receipt_overrides)
    return {**subject, "evidence_verification": receipt}, receipt


def make_learning(verifier):
    return AdaptiveLearning(
        SimpleNamespace(store=object(), evidence_verifier=verifier)
    )


def test_replay_revalidates_bounded_receipt_and_preserves_verifier_fields():
    verifier = AcceptingVerifier()
    learning = make_learning(verifier)
    episode, original_receipt = build_episode()

    assert learning._episode_is_independently_verified(episode) is True
    assert verifier.calls == [
        ("adaptive.record_experience", original_receipt["subject_sha256"])
    ]
    assert verifier.receipt["signature"] == original_receipt["signature"]
    assert verifier.receipt is not original_receipt


@pytest.mark.parametrize(
    "receipt_overrides",
    [
        {"signature": "x" * (AdaptiveLearning.MAX_EVIDENCE_RECEIPT_BYTES + 1)},
        {"signature": object()},
        {"receipt_id": "r" * 257},
        {"verifier_id": "v" * 257},
        {"source_id": "s" * 257},
    ],
)
def test_replay_rejects_oversized_or_non_json_persisted_receipts(receipt_overrides):
    verifier = AcceptingVerifier()
    learning = make_learning(verifier)
    episode, _ = build_episode(**receipt_overrides)

    assert learning._episode_is_independently_verified(episode) is False
    assert verifier.calls == []


def test_replay_rejects_excessively_nested_persisted_receipt():
    verifier = AcceptingVerifier()
    learning = make_learning(verifier)
    nested = None
    for _ in range(14):
        nested = {"nested": nested}
    episode, _ = build_episode(signature=nested)

    assert learning._episode_is_independently_verified(episode) is False
    assert verifier.calls == []


def test_replay_rejects_receipt_with_wrong_subject_binding():
    verifier = AcceptingVerifier()
    learning = make_learning(verifier)
    episode, _ = build_episode(subject_sha256="0" * 64)

    assert learning._episode_is_independently_verified(episode) is False
    assert verifier.calls == []
