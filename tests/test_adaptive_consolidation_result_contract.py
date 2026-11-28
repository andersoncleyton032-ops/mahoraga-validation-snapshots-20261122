from agent.adaptive_learning import AdaptiveLearning


CANDIDATE_ID = "0123456789abcdef01234567"


def _candidate():
    return {
        "candidate_id": CANDIDATE_ID,
        "task_key": "review memory",
        "context_signature": "context-v1",
        "proposed_pattern": "compare independent evidence before promotion",
        "event_ids": ["event-a", "event-b"],
        "source_labels": ["source-a", "source-b"],
        "source_independence_verified": True,
        "validated_episode_count": 2,
        "evidence_state": "independently_verified",
    }


def _expected_memory(candidate):
    value = {
        "task_key": candidate["task_key"],
        "context_signature": candidate["context_signature"],
        "pattern": candidate["proposed_pattern"],
        "event_ids": candidate["event_ids"],
        "source_labels": candidate["source_labels"],
        "source_independence_verified": candidate["source_independence_verified"],
        "validated_episode_count": candidate["validated_episode_count"],
        "evidence_state": candidate["evidence_state"],
        "status": "human_approved_consolidation",
    }
    metadata = {
        "kind": "adaptive_experience_consolidation",
        "candidate_id": CANDIDATE_ID,
        "learning_state": "promoted_from_independently_verified_episodes",
    }
    return value, metadata


class FakeStore:
    def __init__(self):
        self.memories = {}
        self.events = {}
        self.next_event_id = 1

    def get_memory(self, key):
        return self.memories.get(key)

    def record_event_once(self, event_type, idempotency_key, payload=None, severity="info"):
        existing = self.events.get(idempotency_key)
        if existing is not None:
            return {"created": False, "event_id": existing["event_id"]}
        event_id = self.next_event_id
        self.next_event_id += 1
        self.events[idempotency_key] = {
            "event_id": event_id,
            "event_type": event_type,
            "payload": payload,
            "severity": severity,
        }
        return {"created": True, "event_id": event_id}

    def save_memory_if_absent(self, key, value, *, metadata=None):
        if key in self.memories:
            return False
        self.memories[key] = {"value": value, "metadata": metadata or {}}
        return True


class FakeVerifier:
    def __init__(self):
        self.calls = []

    def consume_attestation(self, **kwargs):
        self.calls.append(kwargs)
        return True


class FakeCognitive:
    def __init__(self, store):
        self.store = store
        self.approval_verifier = FakeVerifier()
        self.authorized = []

    def _authorize(self, action):
        self.authorized.append(action)
        return True


def _learner(store, candidate=None):
    cognitive = FakeCognitive(store)
    learner = AdaptiveLearning(cognitive)
    item = _candidate() if candidate is None else candidate
    learner.review_experiences = lambda limit: {
        "review_complete": True,
        "candidates": [item],
    }
    return learner, cognitive, item


def _consolidate(learner):
    return learner.consolidate_candidate(
        CANDIDATE_ID,
        approval_attestation={"token": "opaque-test-attestation"},
    )


def test_existing_memory_without_event_creates_event_and_is_not_duplicate():
    store = FakeStore()
    learner, _, candidate = _learner(store)
    value, metadata = _expected_memory(candidate)
    store.memories[f"adaptive.pattern.{CANDIDATE_ID}"] = {
        "value": value, "metadata": metadata
    }

    result = _consolidate(learner)

    assert result["status"] == "consolidated"
    assert result["event_created"] is True
    assert result["memory_created"] is False
    assert result["duplicate"] is False
    assert len(store.events) == 1


def test_existing_event_without_memory_recovers_memory_and_is_not_duplicate():
    store = FakeStore()
    learner, _, candidate = _learner(store)
    value, metadata = _expected_memory(candidate)
    store.events["adaptive_consolidation:placeholder"] = {
        "event_id": 7, "event_type": "adaptive.experience.consolidated"
    }
    # Seed the exact idempotency key the method will derive.
    request_id = learner._canonical_sha256(candidate)
    from agent.attestation import attestation_request_id
    request_id = attestation_request_id(
        "adaptive.consolidate_candidate",
        {"token": "opaque-test-attestation"},
        request_id,
    )
    store.events["adaptive_consolidation:" + request_id] = {
        "event_id": 8, "event_type": "adaptive.experience.consolidated"
    }

    result = _consolidate(learner)

    assert result["status"] == "consolidated"
    assert result["event_created"] is False
    assert result["memory_created"] is True
    assert result["duplicate"] is False
    assert store.memories[f"adaptive.pattern.{CANDIDATE_ID}"]["value"] == value
    assert store.memories[f"adaptive.pattern.{CANDIDATE_ID}"]["metadata"] == metadata


def test_event_and_memory_both_existing_is_the_only_duplicate_case():
    store = FakeStore()
    learner, _, candidate = _learner(store)
    value, metadata = _expected_memory(candidate)
    key = f"adaptive.pattern.{CANDIDATE_ID}"
    store.memories[key] = {"value": value, "metadata": metadata}
    from agent.attestation import attestation_request_id
    subject_sha256 = learner._canonical_sha256(candidate)
    request_id = attestation_request_id(
        "adaptive.consolidate_candidate",
        {"token": "opaque-test-attestation"},
        subject_sha256,
    )
    store.events["adaptive_consolidation:" + request_id] = {
        "event_id": 9, "event_type": "adaptive.experience.consolidated"
    }

    result = _consolidate(learner)

    assert result["status"] == "already_consolidated"
    assert result["event_created"] is False
    assert result["memory_created"] is False
    assert result["duplicate"] is True


def test_conflicting_existing_memory_blocks_recovery_without_overwrite():
    store = FakeStore()
    learner, cognitive, _ = _learner(store)
    store.memories[f"adaptive.pattern.{CANDIDATE_ID}"] = {
        "value": {"pattern": "different"}, "metadata": {"kind": "different"}
    }

    try:
        _consolidate(learner)
    except RuntimeError as exc:
        assert "diverge" in str(exc).lower()
    else:
        raise AssertionError("Divergent memory must block consolidation.")

    assert store.events == {}
    assert cognitive.approval_verifier.calls == []
