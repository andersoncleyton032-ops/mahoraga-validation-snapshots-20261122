from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import copy
import uuid

import numpy as np
import pytest

from agent.prototype_plasticity import PrototypePlasticity, PrototypePlasticityError


class FakeStore:
    def __init__(self):
        self.events = []
        self.fail_next_write = False
        self.fail_next_read = False

    def record_event(self, event_type, payload):
        if self.fail_next_write:
            self.fail_next_write = False
            raise OSError("simulated durable-write failure")
        event = {
            "id": len(self.events) + 1,
            "event_type": event_type,
            "payload": copy.deepcopy(payload),
        }
        self.events.append(event)
        return event["id"]

    def list_events(self, limit=100, event_type=None):
        if self.fail_next_read:
            self.fail_next_read = False
            raise OSError("simulated persistence read failure")
        events = [
            item for item in self.events
            if event_type is None or item["event_type"] == event_type
        ]
        return list(reversed(events[-limit:]))


class FakeEvidenceVerifier:
    def verify_attestation(self, *, attestation, action, subject_sha256, source):
        if not isinstance(attestation, dict) or not attestation.get("nonce"):
            return None
        return {
            "verified": True,
            "verifier_id": "unit-test-evidence-verifier",
            "receipt_id": str(attestation["nonce"]),
            "subject_sha256": subject_sha256,
            "source_identity_verified": True,
            "source_id": str(source),
        }

    def verify_receipt(self, *, receipt, action, subject_sha256):
        return (
            isinstance(receipt, dict)
            and receipt.get("verified") is True
            and receipt.get("verifier_id") == "unit-test-evidence-verifier"
            and receipt.get("subject_sha256") == subject_sha256
            and receipt.get("source_identity_verified") is True
        )


class FakeApprovalVerifier:
    def __init__(self):
        self.used = set()

    def consume_attestation(self, *, attestation, action, subject_sha256):
        if not isinstance(attestation, dict) or attestation.get("approved") is not True:
            return False
        nonce = attestation.get("nonce")
        if not isinstance(nonce, str) or not nonce or nonce in self.used:
            return False
        self.used.add(nonce)
        return True


class FakeCognitive:
    def __init__(self, store=None):
        self.store = store or FakeStore()
        self.denied = set()
        self.evidence_verifier = FakeEvidenceVerifier()
        self.approval_verifier = FakeApprovalVerifier()

    def _authorize(self, action):
        if action in self.denied:
            raise PermissionError(action)
        return True


def make_learner():
    cognitive = FakeCognitive()
    return PrototypePlasticity(cognitive), cognitive


def learn(learner, vector, label):
    return learner.learn_one(
        vector,
        label,
        approved=True,
        evidence=["human-reviewed-label"],
        source="unit-test",
        approval_attestation={"approved": True, "nonce": uuid.uuid4().hex},
        evidence_attestation={"nonce": uuid.uuid4().hex},
    )


def test_empty_model_abstains_without_mutating_state():
    learner, cognitive = make_learner()

    result = learner.predict([1.0, 0.0])

    assert result["decision"] == "abstain"
    assert result["reason"] == "no_prototypes"
    assert result["prototype_count"] == 0
    assert result["state_modified"] is False
    assert cognitive.store.events == []


def test_learning_requires_approval_and_evidence():
    learner, cognitive = make_learner()

    with pytest.raises(PermissionError):
        learner.learn_one(
            [1.0, 0.0],
            "leaf",
            approved=False,
            evidence=["not-approved"],
        )
    assert cognitive.store.events == []

    with pytest.raises(PrototypePlasticityError):
        learner.learn_one(
            [1.0, 0.0],
            "leaf",
            approved=True,
            evidence=[],
        )
    assert cognitive.store.events == []


def test_caller_boolean_without_trusted_attestations_is_rejected():
    learner, cognitive = make_learner()
    with pytest.raises(PermissionError, match="verificador independente"):
        learner.learn_one(
            [1.0, 0.0],
            "leaf",
            approved=True,
            evidence=["caller-asserted-only"],
        )
    assert learner.status()["prototype_count"] == 0
    assert cognitive.store.events == []


def test_approval_attestation_is_one_shot():
    learner, cognitive = make_learner()
    token = {"approved": True, "nonce": "single-use"}
    learner.learn_one(
        [1.0, 0.0], "leaf", approved=True,
        evidence=["reviewed"], source="unit-test",
        approval_attestation=token,
        evidence_attestation={"nonce": "evidence-first"},
    )
    with pytest.raises(PermissionError, match="já utilizada"):
        learner.learn_one(
            [0.0, 1.0], "stone", approved=True,
            evidence=["reviewed"], source="unit-test",
            approval_attestation=token,
            evidence_attestation={"nonce": "evidence-second"},
        )
    assert learner.status()["prototype_count"] == 1
    assert len(cognitive.store.events) == 1


def test_legacy_unverified_learning_event_is_quarantined():
    learner, cognitive = make_learner()
    prototype = learner._new_prototype(learner._vector([1.0, 0.0]), "legacy")
    cognitive.store.record_event(
        PrototypePlasticity.EVENT_TYPE,
        {
            "version": PrototypePlasticity.VERSION,
            "operation": "prototype_created",
            "prototypes": [learner._state_copy(prototype)],
            "source": "legacy-caller",
            "evidence": ["unverified"],
            "evidence_state": "caller_supplied_not_independently_verified",
        },
    )
    restored = PrototypePlasticity(FakeCognitive(cognitive.store))
    assert restored.status()["prototype_count"] == 0


def test_learning_respects_dharma_authorization():
    learner, cognitive = make_learner()
    cognitive.denied.add("record_learning")

    with pytest.raises(PermissionError):
        learn(learner, [1.0, 0.0], "leaf")

    assert learner.status()["prototype_count"] == 0
    assert cognitive.store.events == []


def test_first_sample_creates_a_prototype_and_predicts():
    learner, cognitive = make_learner()

    result = learn(learner, [1.0, 0.0], "leaf")
    prediction = learner.predict([1.0, 0.0])

    assert result["status"] == "learned"
    assert result["operation"] == "prototype_created"
    assert result["prototype_count"] == 1
    assert result["general_language_model_weights_updated"] is False
    assert prediction["decision"] == "recognize"
    assert prediction["label"] == "leaf"
    assert prediction["state_modified"] is False
    assert len(cognitive.store.events) == 1


def test_successful_reinforcement_reduces_individual_plasticity():
    learner, _ = make_learner()
    learn(learner, [1.0, 0.0], "leaf")
    before = next(iter(learner._prototypes.values()))

    result = learn(learner, [0.98, 0.2], "leaf")
    after = learner._prototypes[before["prototype_id"]]

    assert result["operation"] == "prototype_reinforced"
    assert after["observations"] == 2
    assert after["correct_updates"] == 1
    assert after["goodness"] > before["goodness"]
    assert after["plasticity"] < before["plasticity"]


def test_contradictory_label_increases_old_prototype_plasticity_and_adds_new():
    learner, _ = make_learner()
    learn(learner, [1.0, 0.0], "leaf")
    original = next(iter(learner._prototypes.values()))

    result = learn(learner, [1.0, 0.0], "stone")
    revised_original = learner._prototypes[original["prototype_id"]]

    assert result["conflict_detected"] is True
    assert result["operation"] == "prototype_created"
    assert result["prototype_count"] == 2
    assert revised_original["misclassifications"] == 1
    assert revised_original["plasticity"] > original["plasticity"]
    # Conflicting equally similar labels must not be reported as a confident hit.
    prediction = learner.predict([1.0, 0.0])
    assert prediction["decision"] == "abstain"
    assert prediction["reason"] == "ambiguous_prototype_margin"


def test_novel_sample_is_not_forced_into_an_existing_class():
    learner, _ = make_learner()
    learn(learner, [1.0, 0.0], "leaf")

    result = learner.predict([0.0, 1.0])

    assert result["decision"] == "novel"
    assert result["label"] is None
    assert result["learning_performed"] is False


def test_feature_validation_and_dimension_mismatch():
    learner, _ = make_learner()

    with pytest.raises(PrototypePlasticityError):
        learner.predict([0.0, 0.0])
    with pytest.raises(PrototypePlasticityError):
        learner.predict([float("nan"), 1.0])

    learn(learner, [1.0, 0.0], "leaf")
    with pytest.raises(PrototypePlasticityError):
        learner.predict([1.0, 0.0, 0.0])
    with pytest.raises(PrototypePlasticityError):
        learn(learner, [1.0, 0.0, 0.0], "leaf")


def test_failed_durable_write_does_not_change_in_memory_state():
    learner, cognitive = make_learner()
    cognitive.store.fail_next_write = True

    with pytest.raises(OSError):
        learn(learner, [1.0, 0.0], "leaf")

    assert learner.status()["prototype_count"] == 0
    assert cognitive.store.events == []


def test_failed_capacity_check_does_not_partially_update_conflict():
    learner, cognitive = make_learner()
    learn(learner, [1.0, 0.0], "leaf")
    original = copy.deepcopy(next(iter(learner._prototypes.values())))
    learner.MAX_PROTOTYPES = 1

    with pytest.raises(PrototypePlasticityError):
        learn(learner, [1.0, 0.0], "stone")

    current = learner._prototypes[original["prototype_id"]]
    assert current == original
    assert len(cognitive.store.events) == 1


def test_prototype_state_survives_reconstruction_from_append_only_store():
    learner, cognitive = make_learner()
    learn(learner, [1.0, 0.0], "leaf")
    learn(learner, [0.98, 0.2], "leaf")

    restored = PrototypePlasticity(FakeCognitive(cognitive.store))
    prediction = restored.predict([1.0, 0.0])
    state = restored.state_dict()

    assert prediction["decision"] == "recognize"
    assert prediction["label"] == "leaf"
    assert state["schema"] == "mahoraga.prototype_plasticity"
    assert state["prototype_count"] == 1
    assert len(state["sha256"]) == 64


def test_checkpoint_snapshot_restores_state(monkeypatch):
    monkeypatch.setattr(PrototypePlasticity, "CHECKPOINT_INTERVAL", 2)
    learner, cognitive = make_learner()
    learn(learner, [1.0, 0.0], "leaf")
    learn(learner, [0.0, 1.0], "stone")
    learner._checkpoint()

    checkpoints = [
        event for event in cognitive.store.events
        if event["event_type"] == PrototypePlasticity.CHECKPOINT_EVENT
    ]
    assert len(checkpoints) == 1

    # Legacy unsigned snapshots are ignored; authenticated deltas remain the
    # restoration authority until a signed checkpoint format is implemented.
    restored = PrototypePlasticity(FakeCognitive(cognitive.store))
    assert restored.status()["prototype_count"] == 2
    assert restored.predict([1.0, 0.0])["label"] == "leaf"


def test_state_dict_is_stable_and_does_not_train_or_write():
    learner, cognitive = make_learner()
    learn(learner, [1.0, 0.0], "leaf")
    before = len(cognitive.store.events)

    first = learner.state_dict()
    second = learner.state_dict()

    assert first["sha256"] == second["sha256"]
    assert first["prototypes"] == second["prototypes"]
    assert len(cognitive.store.events) == before
    assert learner.status()["evidence_independently_verified"] is True

def test_integrated_core_shares_and_reports_prototype_plasticity(tmp_path):
    from agent.integration_core import IntegratedCore
    from agent.store import KnowledgeStore

    class FakeHardware:
        def snapshot(self):
            return {
                "android": {"model": "test-device"},
                "available_tools": {"python": "/usr/bin/python"},
            }

    store = KnowledgeStore(tmp_path / "prototype-integration.sqlite3")
    core = IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=FakeHardware(),
    )

    assert core.prototype_plasticity is core.cognitive.prototype_plasticity
    assert core.prototype_plasticity.store is store

    report = core.prepare_request(
        "Quero estudar uma planta.",
        include_capability_review=False,
        include_experience_review=False,
    )

    assert report["prototype_plasticity"]["prototype_count"] == 0
    assert any(
        stage["stage"] == "prototype_plasticity"
        and stage["status"] == "untrained"
        for stage in report["pipeline"]
    )
    assert report["side_effects"]["prototype_learning_performed"] is False
    assert report["side_effects"]["neural_training_performed"] is False



def test_invalid_latest_checkpoint_falls_back_and_replays_later_deltas(monkeypatch):
    monkeypatch.setattr(PrototypePlasticity, "CHECKPOINT_INTERVAL", 2)
    learner, cognitive = make_learner()

    learn(learner, [1.0, 0.0], "leaf")
    learn(learner, [0.0, 1.0], "stone")
    learner._checkpoint()

    valid_checkpoints = [
        event for event in cognitive.store.events
        if event["event_type"] == PrototypePlasticity.CHECKPOINT_EVENT
    ]
    assert len(valid_checkpoints) == 1

    cognitive.store.record_event(
        PrototypePlasticity.CHECKPOINT_EVENT,
        {
            "version": PrototypePlasticity.VERSION,
            "prototype_count": 2,
            "prototypes": [{"prototype_id": "truncated-checkpoint"}],
        },
    )

    learn(learner, [0.98, 0.2], "leaf")
    restored = PrototypePlasticity(FakeCognitive(cognitive.store))

    state = restored.state_dict()
    leaf = next(item for item in state["prototypes"] if item["label"] == "leaf")
    assert state["prototype_count"] == 2
    assert leaf["observations"] == 2
    assert restored.predict([1.0, 0.0])["label"] == "leaf"


def test_persistence_read_failure_is_not_misreported_as_empty_model():
    store = FakeStore()
    store.fail_next_read = True

    with pytest.raises(OSError, match="persistence read failure"):
        PrototypePlasticity(FakeCognitive(store))


def test_restore_refuses_truncated_delta_history_without_valid_checkpoint():
    store = FakeStore()
    store.events = [
        {
            "id": event_id,
            "event_type": PrototypePlasticity.EVENT_TYPE,
            "payload": {"version": PrototypePlasticity.VERSION, "prototypes": []},
        }
        for event_id in range(1, PrototypePlasticity.RESTORE_EVENT_LIMIT + 1)
    ]

    with pytest.raises(PrototypePlasticityError, match="checkpoint criptograficamente verificável; restauração recusada"):
        PrototypePlasticity(FakeCognitive(store))


def test_shared_learner_serializes_concurrent_reads_and_updates():
    learner, cognitive = make_learner()
    learn(learner, [1.0, 0.0], "leaf")

    original_rank = learner._rank
    tracker_lock = Lock()
    active_rank_calls = 0
    maximum_active_rank_calls = 0

    def tracked_rank(vector):
        nonlocal active_rank_calls, maximum_active_rank_calls
        with tracker_lock:
            active_rank_calls += 1
            maximum_active_rank_calls = max(
                maximum_active_rank_calls, active_rank_calls
            )
        try:
            # Yield execution so unsynchronized callers would overlap.
            sleep(0.002)
            return original_rank(vector)
        finally:
            with tracker_lock:
                active_rank_calls -= 1

    learner._rank = tracked_rank
    update_count = 32
    read_count = 32

    def update(index):
        return learner.learn_one(
            [1.0, (index + 1) * 0.0001],
            "leaf",
            approved=True,
            evidence=[f"concurrent-test:{index}"],
            source="threaded-unit-test",
            approval_attestation={"approved": True, "nonce": uuid.uuid4().hex},
            evidence_attestation={"nonce": uuid.uuid4().hex},
        )

    def read(index):
        if index % 3 == 0:
            return learner.predict([1.0, 0.0005])
        if index % 3 == 1:
            return learner.state_dict()
        return learner.status()

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [
            executor.submit(update, index)
            for index in range(update_count)
        ] + [
            executor.submit(read, index)
            for index in range(read_count)
        ]
        results = [future.result(timeout=10) for future in futures]

    state = learner.state_dict()
    prototype = state["prototypes"][0]
    assert maximum_active_rank_calls == 1
    assert prototype["observations"] == update_count + 1
    assert prototype["correct_updates"] == update_count
    assert len(cognitive.store.events) == update_count + 1
    assert sum(item.get("status") == "learned" for item in results) == update_count

    restored = PrototypePlasticity(FakeCognitive(cognitive.store))
    restored_state = restored.state_dict()
    assert restored_state["prototypes"][0]["observations"] == update_count + 1
    assert restored.predict([1.0, 0.0005])["label"] == "leaf"


def test_malformed_checkpoint_with_unrepresentable_numbers_is_skipped():
    learner, _ = make_learner()
    learn(learner, [1.0, 0.0], "leaf")
    state = learner.state_dict()["prototypes"][0]
    state["plasticity"] = 10 ** 10000

    assert PrototypePlasticity._validate_state(state) is None
