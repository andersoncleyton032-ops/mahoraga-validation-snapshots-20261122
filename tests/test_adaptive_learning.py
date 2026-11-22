import pytest

from agent.dharma import Dharma, Decision
from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore


class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


class TestEvidenceVerifier:
    def verify_attestation(self, *, attestation, action, subject_sha256, source):
        if not isinstance(attestation, dict) or attestation.get("nonce") is None:
            return None
        return {
            "verified": True,
            "verifier_id": "unit-test-evidence-verifier",
            "receipt_id": str(attestation["nonce"]),
            "subject_sha256": subject_sha256,
            "source_identity_verified": True,
            "source_id": str(attestation.get("source_id", source)),
        }

    def verify_receipt(self, *, receipt, action, subject_sha256):
        return (
            isinstance(receipt, dict)
            and receipt.get("verified") is True
            and receipt.get("subject_sha256") == subject_sha256
            and receipt.get("verifier_id") == "unit-test-evidence-verifier"
            and receipt.get("source_identity_verified") is True
            and isinstance(receipt.get("source_id"), str)
            and bool(receipt.get("source_id"))
        )


class ApprovalVerifierFixture:
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


def make_core(tmp_path, dharma=None):
    store = KnowledgeStore(tmp_path / "adaptive.sqlite3")
    core = IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=FakeHardware(),
        dharma=dharma,
    )
    core.cognitive.evidence_verifier = TestEvidenceVerifier()
    core.cognitive.approval_verifier = ApprovalVerifierFixture()
    return core, store


def add_episode(core, task, outcome, source, index, context=None):
    return core.cognitive.record_experience(
        task=task,
        action=f"action-{index}",
        outcome=outcome,
        source=source,
        expected_outcome=outcome,
        confidence=0.9,
        validation_evidence=[f"test-report-{index}"],
        evidence_attestation={"nonce": f"episode-{index}-{source}", "source_id": source},
        validated=True,
        tags=["learning", "test"],
        context=context,
    )





def persist_research_plan(
    store, plan_id, candidate_id, initiative_kind, initiative_source
):
    plan = {
        "schema": "mahoraga.research_plan",
        "plan_id": plan_id,
        "candidate_id": candidate_id,
        "initiative_kind": initiative_kind,
        "source": initiative_source,
        "status": "prepared_pending_execution_review",
    }
    assert store.save_memory_if_absent(
        f"research_plan:{plan_id}",
        plan,
        {"kind": "research_plan"},
    ) is True

def test_adaptive_learning_is_owned_by_shared_cognitive_core(tmp_path):
    core, store = make_core(tmp_path)
    adaptive = core.cognitive.adaptive_learning
    assert adaptive.cognitive is core.cognitive
    assert adaptive.store is store
    assert core.cognitive.review_experiences()["replayed_episode_count"] == 0


def test_experience_recording_is_episodic_not_semantic_learning(tmp_path):
    core, store = make_core(tmp_path)
    before = store.load_memories()
    result = add_episode(core, "test parser", "passed", "ci-a", 1)
    assert result["status"] == "episode_recorded"
    assert result["learning_state"] == "episodic_only"
    assert result["neural_training_performed"] is False
    assert store.load_memories() == before
    events = store.list_events(limit=10, event_type="adaptive.experience.recorded")
    assert len(events) == 1
    assert events[0]["payload"]["prediction_error"] == 0.0


def test_prediction_error_is_computed_from_expected_and_observed_outcome(tmp_path):
    core, _ = make_core(tmp_path)
    result = core.cognitive.record_experience(
        "test parser", "run test", "failed", "ci-a",
        expected_outcome="passed", confidence=0.8,
    )
    assert result["prediction_error"] == 1.0


def test_replay_requires_repeated_independent_validated_evidence(tmp_path):
    core, _ = make_core(tmp_path)
    add_episode(core, "test parser", "passed", "ci-a", 1)
    add_episode(core, "test parser", "passed", "ci-b", 2)
    add_episode(core, "test parser", "passed", "ci-c", 3)
    result = core.cognitive.review_experiences()
    assert result["replayed_episode_count"] == 3
    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["episode_count"] == 3
    assert candidate["validated_episode_count"] == 3
    assert candidate["status"] == "candidate_requires_human_approval"
    assert result["memory_modified"] is False
    assert result["neural_training_performed"] is False


def test_replay_does_not_promote_single_source_or_unvalidated_episodes(tmp_path):
    core, _ = make_core(tmp_path)
    for index in range(4):
        core.cognitive.record_experience(
            "test parser", "run", "passed", "same-source",
            confidence=0.99, validated=False,
        )
    result = core.cognitive.review_experiences()
    assert result["candidate_count"] == 0


def test_consolidation_requires_explicit_approval_and_rechecks_evidence(tmp_path):
    core, store = make_core(tmp_path)
    for index, source in enumerate(("ci-a", "ci-b", "ci-c"), 1):
        add_episode(core, "test parser", "passed", source, index)
    candidate = core.cognitive.review_experiences()["candidates"][0]
    before = store.load_memories()
    try:
        core.cognitive.consolidate_experience(candidate["candidate_id"])
    except PermissionError:
        pass
    else:
        raise AssertionError("Consolidação sem aprovação foi aceita.")
    assert store.load_memories() == before

    with pytest.raises(PermissionError):
        core.cognitive.consolidate_experience(
            candidate["candidate_id"], approved=True
        )

    result = core.cognitive.consolidate_experience(
        candidate["candidate_id"], approved=True,
        approval_attestation={"approved": True, "nonce": "promotion-once"},
    )
    assert result["status"] == "consolidated"
    assert result["neural_training_performed"] is False
    assert result["memory_key"] in store.load_memories()
    with pytest.raises(PermissionError):
        core.cognitive.consolidate_experience(
            candidate["candidate_id"], approved=True,
            approval_attestation={"approved": True, "nonce": "promotion-once"},
        )


def test_consolidation_rejects_stale_or_forged_candidate(tmp_path):
    core, _ = make_core(tmp_path)
    try:
        core.cognitive.consolidate_experience("0" * 24, approved=True)
    except ValueError:
        pass
    else:
        raise AssertionError("Candidato inexistente foi aceito.")


def test_dharma_can_block_experience_recording(tmp_path):
    class DenyExperience(Dharma):
        def evaluate(self, action, target="", context=None):
            if action == "record_observation":
                return Decision(
                    allowed=False, requires_approval=True,
                    reason="Experiência bloqueada.", risk_score=70,
                    category="test", reversible=True,
                )
            return super().evaluate(action, target, context)

    core, store = make_core(tmp_path, dharma=DenyExperience(tmp_path))
    try:
        core.cognitive.record_experience(
            "task", "action", "outcome", "source"
        )
    except PermissionError as exc:
        assert "Experiência bloqueada" in str(exc)
    else:
        raise AssertionError("Dharma não bloqueou o registro.")
    assert store.list_events(limit=10, event_type="adaptive.experience.recorded") == []


def test_integrated_request_can_include_read_only_experience_replay(tmp_path):
    core, store = make_core(tmp_path)
    add_episode(core, "test parser", "passed", "ci-a", 1)
    core.language.classify = lambda _: {
        "recognized": False, "decision": "abstain",
        "intent": None, "reason": "test",
    }
    before = store.counts()
    result = core.prepare_request(
        "Como está o histórico de experiências?",
        include_capability_review=False,
        include_experience_review=True,
    )
    assert result["experience_review"]["status"] == "reviewed"
    assert result["experience_review"]["result"]["replayed_episode_count"] == 1
    assert result["experience_review"]["result"]["review_complete"] is True
    assert result["experience_review"]["result"]["window_truncated"] is False
    experience_stage = next(
        item for item in result["pipeline"]
        if item["stage"] == "experience_replay"
    )
    assert experience_stage["status"] == "reviewed"
    assert result["side_effects"]["learning_persisted"] is False
    assert store.counts() == before


def test_experience_inputs_reject_invalid_confidence_and_validation_claims(tmp_path):
    core, _ = make_core(tmp_path)
    for confidence in (True, -0.1, 1.1, float("nan"), 10**10000):
        try:
            core.cognitive.record_experience(
                "task", "action", "outcome", "source",
                confidence=confidence,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"Confiança inválida aceita: {confidence!r}")
    try:
        core.cognitive.record_experience(
            "task", "action", "outcome", "source",
            validated=True,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Validação sem evidência foi aceita.")



def test_full_task_identity_prevents_first_twelve_token_collisions(tmp_path):
    core, _ = make_core(tmp_path)
    shared = "inspecionar diagnostico completo do sistema " * 4
    cpu_task = shared + "cpu"
    gpu_task = shared + "gpu"
    for index, source in enumerate(("ci-a", "ci-b", "ci-c"), 1):
        add_episode(core, cpu_task, "passed", source, index)
        add_episode(core, gpu_task, "passed", source, index + 10)

    result = core.cognitive.review_experiences()
    assert result["candidate_count"] == 2
    assert {item["task_key"] for item in result["candidates"]} == {
        core.cognitive.adaptive_learning._task_key(cpu_task),
        core.cognitive.adaptive_learning._task_key(gpu_task),
    }


def test_context_signatures_prevent_cross_environment_consolidation(tmp_path):
    core, _ = make_core(tmp_path)
    for index, device in enumerate(("realme", "emulator", "desktop"), 1):
        add_episode(
            core, "executar testes de integração", "passed", f"source-{index}",
            index, context={"device": device, "python": "3.14"},
        )
    result = core.cognitive.review_experiences()
    assert result["candidate_count"] == 0


def test_unvalidated_high_confidence_does_not_raise_validated_mean(tmp_path):
    core, _ = make_core(tmp_path)
    for index, source in enumerate(("ci-a", "ci-b"), 1):
        core.cognitive.record_experience(
            "test parser", f"action-{index}", "passed", source,
            confidence=0.6, validation_evidence=[f"report-{index}"],
            validated=True,
        )
    core.cognitive.record_experience(
        "test parser", "action-3", "passed", "ci-c",
        confidence=1.0, validated=False,
    )
    result = core.cognitive.review_experiences()
    assert result["candidate_count"] == 0


def test_candidate_discloses_unverified_source_independence(tmp_path):
    core, _ = make_core(tmp_path)
    for index, source in enumerate(("ci-a", "ci-b", "ci-c"), 1):
        add_episode(core, "test parser", "passed", source, index)
    candidate = core.cognitive.review_experiences()["candidates"][0]
    assert candidate["source_independence_verified"] is True
    assert candidate["evidence_state"] == "independently_verified_by_configured_verifier"
    assert candidate["mean_validated_confidence"] == 0.9


def test_caller_validation_claim_without_verifier_never_creates_candidate(tmp_path):
    core, _ = make_core(tmp_path)
    core.cognitive.evidence_verifier = None
    for index, source in enumerate(("ci-a", "ci-b", "ci-c"), 1):
        add_episode(core, "test parser", "passed", source, index)
    result = core.cognitive.review_experiences()
    assert result["candidate_count"] == 0
    assert result["learning_policy"]["source_diversity"] == "verifier_authenticated_source_ids"


def test_context_rejects_non_json_and_oversized_values(tmp_path):
    core, store = make_core(tmp_path)
    for context in ({"not_finite": float("nan")}, {"payload": "x" * 5000}):
        try:
            core.cognitive.record_experience(
                "task", "action", "outcome", "source", context=context
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Contexto inválido foi aceito.")
    assert store.list_events(event_type="adaptive.experience.recorded") == []



def test_invalid_evidence_container_and_empty_task_are_rejected(tmp_path):
    core, store = make_core(tmp_path)
    with pytest.raises(ValueError):
        core.cognitive.record_experience(
            "!!!", "action", "outcome", "source"
        )
    with pytest.raises(ValueError):
        core.cognitive.record_experience(
            "task", "action", "outcome", "source",
            validation_evidence="",
        )
    assert store.list_events(event_type="adaptive.experience.recorded") == []



def test_research_results_are_idempotent_unverified_episodic_experiences(tmp_path):
    core, store = make_core(tmp_path)
    kwargs = {
        "plan_id": "research-" + "d" * 24,
        "candidate_id": "inquiry:" + "e" * 24,
        "initiative_kind": "self_inquiry",
        "initiative_source": "persisted_self_inquiry",
        "method": "Comparar a recuperação antes e depois do checkpoint.",
        "result_status": "completed",
        "summary": "O teste de recuperação terminou sem erros observados.",
        "evidence_refs": ["ci://run/589", "sha256:" + "f" * 64],
        "approved": True,
    }
    persist_research_plan(
        store,
        kwargs["plan_id"],
        kwargs["candidate_id"],
        kwargs["initiative_kind"],
        kwargs["initiative_source"],
    )

    first = core.cognitive.record_research_result(**kwargs)
    repeated = core.cognitive.record_research_result(**kwargs)

    assert first["status"] == "research_result_recorded"
    assert first["event_created"] is True
    assert repeated["event_created"] is False
    assert repeated["event_id"] == first["event_id"]
    assert first["learning_state"] == "episodic_only"
    assert first["independently_verified"] is False
    assert first["semantic_consolidation_performed"] is False

    events = store.list_events(
        limit=20, event_type="adaptive.experience.recorded"
    )
    assert len(events) == 1
    episode = events[0]["payload"]
    assert episode["validated"] is False
    assert episode["validation_state"] == "not_validated"
    assert episode["references"]["research_plan_id"] == kwargs["plan_id"]
    assert episode["references"]["evidence_refs"] == kwargs["evidence_refs"]

    replay = core.cognitive.review_experiences()
    assert replay["replayed_episode_count"] == 1
    assert replay["candidate_count"] == 0


def test_research_result_idempotency_rejects_changed_report(tmp_path):
    core, store = make_core(tmp_path)
    base = {
        "plan_id": "research-" + "1" * 24,
        "candidate_id": "capability:" + "2" * 24,
        "initiative_kind": "capability_gap",
        "initiative_source": "capability_audit",
        "method": "Executar o benchmark local.",
        "result_status": "completed",
        "summary": "Primeiro relatório.",
        "evidence_refs": ["artifact://first"],
        "approved": True,
    }
    persist_research_plan(
        store,
        base["plan_id"],
        base["candidate_id"],
        base["initiative_kind"],
        base["initiative_source"],
    )
    core.cognitive.record_research_result(**base)

    changed = dict(base, summary="Relatório alterado.")
    with pytest.raises(ValueError, match="outro conteúdo"):
        core.cognitive.record_research_result(**changed)

    assert len(store.list_events(
        event_type="adaptive.experience.recorded"
    )) == 1


def test_research_result_rejects_invalid_status_or_missing_evidence(tmp_path):
    core, store = make_core(tmp_path)
    common = {
        "plan_id": "research-" + "3" * 24,
        "candidate_id": "experience:" + "4" * 24,
        "initiative_kind": "experience_pattern",
        "initiative_source": "adaptive_learning",
        "method": "Comparação controlada.",
        "result_status": "unknown",
        "summary": "Resultado.",
        "evidence_refs": ["report://one"],
        "approved": True,
    }
    persist_research_plan(
        store,
        common["plan_id"],
        common["candidate_id"],
        common["initiative_kind"],
        common["initiative_source"],
    )
    with pytest.raises(ValueError, match="result_status"):
        core.cognitive.record_research_result(**common)

    common["result_status"] = "completed"
    common["evidence_refs"] = []
    with pytest.raises(ValueError, match="evidence_refs"):
        core.cognitive.record_research_result(**common)

    assert store.list_events(
        event_type="adaptive.experience.recorded"
    ) == []


def record_numeric_prediction(
    core, error, index, *, predictor_id="latency-model-v1",
    metric="latency_ms", context=None, source=None,
):
    return core.cognitive.record_experience(
        task="predict runtime latency",
        action=f"predict sample {index}",
        outcome="measurement recorded",
        source=source or f"sensor-{index % 3}",
        prediction=0.0,
        observed=float(error) * 100.0,
        prediction_scale=100.0,
        prediction_metric=metric,
        predictor_id=predictor_id,
        confidence=0.5,
        context=context or {"device": "fixture"},
    )


def test_numeric_prediction_error_is_normalized_and_keeps_provenance(tmp_path):
    core, store = make_core(tmp_path)

    result = record_numeric_prediction(core, 0.25, 1)

    assert result["prediction_error"] == 0.25
    assert result["prediction_error_kind"] == "normalized_mae_v1"
    episode = store.list_events(
        limit=1, event_type="adaptive.experience.recorded"
    )[0]["payload"]
    assert episode["prediction_details"]["metric"] == "latency_ms"
    assert episode["prediction_details"]["predictor_id"] == "latency-model-v1"
    assert episode["prediction_details"]["normalization_scale"] == 100.0
    assert episode["learning_state"] == "episodic_only"
    assert episode["neural_training_performed"] is False
    review = core.cognitive.review_experiences()
    assert review["prediction_error_rate"] is None
    assert review["normalized_prediction_error_mean"] == 0.25
    assert review["normalized_prediction_error_sample_count"] == 1


def test_numeric_prediction_inputs_reject_mismatched_or_nonfinite_vectors(tmp_path):
    core, store = make_core(tmp_path)
    invalid = [
        {"prediction": 1.0},
        {"prediction": [1.0, 2.0], "observed": [1.0]},
        {"prediction": [1.0, float("nan")], "observed": [1.0, 2.0]},
        {"prediction": 1.0, "observed": 2.0, "prediction_scale": 0.0},
    ]
    for index, values in enumerate(invalid):
        kwargs = {
            "prediction_scale": 1.0,
            "prediction_metric": "error",
            "predictor_id": "test-model",
        }
        kwargs.update(values)
        with pytest.raises(ValueError):
            core.cognitive.record_experience(
                "numeric task", f"action-{index}", "observed", "test",
                **kwargs,
            )
    assert store.list_events(
        event_type="adaptive.experience.recorded"
    ) == []


def test_learning_progress_is_estimated_from_comparable_error_windows(tmp_path):
    core, _ = make_core(tmp_path)
    errors = [0.8, 0.7, 0.6, 0.3, 0.2, 0.1]
    for index, error in enumerate(errors):
        record_numeric_prediction(core, error, index)

    review = core.cognitive.review_experiences()
    progress = review["prediction_progress"][0]

    assert progress["status"] == "progress_observed"
    assert progress["sample_count"] == 6
    assert progress["early_mean_error"] == 0.7
    assert progress["recent_mean_error"] == 0.2
    assert progress["learning_progress"] > 0.7
    assert progress["uncertainty_reducible"] > 0.0
    assert review["prediction_progress_group_count"] == 1


def test_noisy_or_worsening_prediction_does_not_receive_progress_reward(tmp_path):
    core, _ = make_core(tmp_path)
    errors = [0.2, 0.8, 0.2, 0.8, 0.2, 0.8]
    for index, error in enumerate(errors):
        record_numeric_prediction(core, error, index)

    progress = core.cognitive.review_experiences()["prediction_progress"][0]

    assert progress["status"] == "regression_observed"
    assert progress["learning_progress"] == 0.0
    assert progress["uncertainty_reducible"] == 0.0
    assert progress["prediction_regression"] > 0.0


def test_prediction_progress_never_mixes_contexts_or_predictor_versions(tmp_path):
    core, _ = make_core(tmp_path)
    for index, error in enumerate([0.8, 0.7, 0.6]):
        record_numeric_prediction(
            core, error, index, context={"device": "realme"},
            predictor_id="model-a",
        )
    for index, error in enumerate([0.3, 0.2, 0.1], 3):
        record_numeric_prediction(
            core, error, index, context={"device": "emulator"},
            predictor_id="model-b",
        )

    review = core.cognitive.review_experiences()

    assert review["prediction_progress_group_count"] == 2
    assert all(item["status"] == "insufficient_samples"
               for item in review["prediction_progress"])


def test_measured_learning_progress_flows_into_executive_initiative_ranking(tmp_path):
    core, _ = make_core(tmp_path)
    errors = [0.8, 0.7, 0.6, 0.3, 0.2, 0.1]
    for index, error in enumerate(errors):
        core.cognitive.record_experience(
            task="predict runtime latency",
            action=f"predict sample {index}",
            outcome="measurement recorded",
            source=f"independent-fixture-{index % 3}",
            prediction=0.0,
            observed=error * 100.0,
            prediction_scale=100.0,
            prediction_metric="latency_ms",
            predictor_id="latency-model-v1",
            confidence=0.9,
            validation_evidence=[f"fixture-report-{index}"],
            evidence_attestation={
                "nonce": f"latency-model-v1-{index}",
                "source_id": f"independent-fixture-{index % 3}",
            },
            validated=True,
            context={"device": "fixture"},
        )

    review = core.cognitive.review_initiatives()
    candidate = next(
        item for item in review["candidates"]
        if item["kind"] == "experience_pattern"
    )

    assert candidate["evidence"]["learning_progress"] > 0.7
    assert candidate["evidence"]["uncertainty_reducible"] > 0.0
    assert candidate["evidence"]["prediction_sample_count"] == 6
    assert candidate["evidence"]["source_independence_verified"] is False
    assert review["execution_performed"] is False



def test_numeric_prediction_rejects_unrepresentably_large_integer_without_persisting(tmp_path):
    core, store = make_core(tmp_path)
    with pytest.raises(ValueError, match="representáveis"):
        core.cognitive.record_experience(
            "numeric task", "action", "observed", "test",
            prediction=10 ** 10000,
            observed=0.0,
            prediction_scale=1.0,
            prediction_metric="error",
            predictor_id="test-model",
        )
    with pytest.raises(ValueError, match="prediction_scale"):
        core.cognitive.record_experience(
            "numeric task", "action", "observed", "test",
            prediction=1.0,
            observed=0.0,
            prediction_scale=10 ** 10000,
            prediction_metric="error",
            predictor_id="test-model",
        )
    assert store.list_events(event_type="adaptive.experience.recorded") == []


def test_progress_is_not_averaged_across_distinct_predictors(tmp_path):
    core, _ = make_core(tmp_path)
    for index, error in enumerate([0.8, 0.7, 0.6, 0.3, 0.2, 0.1]):
        core.cognitive.record_experience(
            task="predict runtime latency",
            action=f"model-a sample {index}",
            outcome="measurement recorded",
            source=f"source-a-{index}",
            prediction=0.0,
            observed=error * 100.0,
            prediction_scale=100.0,
            prediction_metric="latency_ms",
            predictor_id="model-a",
            confidence=0.9,
            validation_evidence=[f"evidence-a-{index}"],
            evidence_attestation={
                "nonce": f"model-a-{index}",
                "source_id": f"source-a-{index}",
            },
            validated=True,
            context={"device": "fixture"},
        )
    for index, error in enumerate([0.1, 0.2]):
        core.cognitive.record_experience(
            task="predict runtime latency",
            action=f"model-b sample {index}",
            outcome="measurement recorded",
            source=f"source-b-{index}",
            prediction=0.0,
            observed=error * 100.0,
            prediction_scale=100.0,
            prediction_metric="latency_ms",
            predictor_id="model-b",
            confidence=0.9,
            validation_evidence=[f"evidence-b-{index}"],
            evidence_attestation={
                "nonce": f"model-b-{index}",
                "source_id": f"source-b-{index}",
            },
            validated=True,
            context={"device": "fixture"},
        )

    review = core.cognitive.review_experiences()
    candidate = next(
        item for item in review["candidates"]
        if item["task_key"] == "predict runtime latency"
    )

    assert candidate["prediction_progress_ambiguous"] is True
    assert candidate["learning_progress"] == 0.0
    assert candidate["uncertainty_reducible"] == 0.0
    assert candidate["prediction_sample_count"] == 8

def test_replay_exposes_total_history_and_truncated_window(tmp_path):
    core, store = make_core(tmp_path)
    add_episode(core, "test parser", "passed", "ci-a", 1)
    add_episode(core, "test parser", "passed", "ci-b", 2)
    add_episode(core, "test parser", "passed", "ci-c", 3)

    review = core.cognitive.review_experiences(limit=2)
    status = core.cognitive.adaptive_learning.status()

    assert review["events_examined"] == 2
    assert review["total_recorded_episodes"] == 3
    assert review["window_limit"] == 2
    assert review["window_truncated"] is True
    assert review["review_complete"] is False
    assert review["history_status"] == "incomplete"
    assert status["episode_count_in_window"] == 3
    assert status["episode_count_total"] == 3
    assert status["window_truncated"] is False
    assert status["history_complete"] is True


def test_consolidation_fails_closed_when_replay_history_is_truncated(tmp_path):
    core, store = make_core(tmp_path)
    for index, source in enumerate(("ci-a", "ci-b", "ci-c"), 1):
        add_episode(core, "test parser", "passed", source, index)
    candidate = core.cognitive.review_experiences()["candidates"][0]
    original_count_events = store.count_events

    def report_older_history(event_type=None):
        count = original_count_events(event_type=event_type)
        if event_type == core.cognitive.adaptive_learning.EVENT_TYPE:
            return count + 1
        return count

    store.count_events = report_older_history

    with pytest.raises(PermissionError, match="histórico está incompleto"):
        core.cognitive.consolidate_experience(
            candidate["candidate_id"],
            approved=True,
            approval_attestation={"approved": True, "nonce": "must-not-consume"},
        )

    assert core.cognitive.approval_verifier.used == set()
    assert not any(
        key.startswith("adaptive.pattern.")
        for key in store.load_memories()
    )

def test_incomplete_replay_suppresses_partial_candidates(tmp_path):
    core, _ = make_core(tmp_path)
    for index, source in enumerate(("ci-a", "ci-b", "ci-c", "ci-d"), 1):
        add_episode(core, "test parser", "passed", source, index)

    review = core.cognitive.review_experiences(limit=3)

    assert review["window_truncated"] is True
    assert review["review_complete"] is False
    assert review["candidate_count_before_history_guard"] == 1
    assert review["candidate_proposals_suppressed"] is True
    assert review["candidate_count"] == 0
    assert review["candidates"] == []


def test_replay_marks_malformed_event_envelopes_as_incomplete(tmp_path):
    core, store = make_core(tmp_path)
    with store._transaction() as db:
        db.execute(
            """INSERT INTO events(event_type, severity, payload_json, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                core.cognitive.adaptive_learning.EVENT_TYPE,
                "info",
                "[]",
                "2026-11-17T00:00:00+00:00",
            ),
        )

    review = core.cognitive.review_experiences()
    status = core.cognitive.adaptive_learning.status()

    assert review["total_recorded_episodes"] == 1
    assert review["invalid_episode_event_count"] == 1
    assert review["review_complete"] is False
    assert review["candidate_proposals_suppressed"] is True
    assert status["invalid_episode_event_count"] == 1
    assert status["history_complete"] is False




def test_experience_recall_is_context_bound_read_only_and_trust_ranked(tmp_path):
    core, store = make_core(tmp_path)
    context = {"app": "Blender", "scene_kind": "camera_test"}
    verified = add_episode(
        core,
        "criar e configurar câmera orbit no Blender",
        "passed",
        "verified-ci",
        1,
        context=context,
    )
    assert verified["status"] == "episode_recorded"

    class MixedEvidenceVerifier(TestEvidenceVerifier):
        def verify_attestation(self, *, attestation, action, subject_sha256, source):
            if source == "unverified-user-report":
                return None
            return super().verify_attestation(
                attestation=attestation,
                action=action,
                subject_sha256=subject_sha256,
                source=source,
            )

    core.cognitive.evidence_verifier = MixedEvidenceVerifier()
    unverified = add_episode(
        core,
        "criar câmera orbit no Blender",
        "passed",
        "unverified-user-report",
        2,
        context=context,
    )
    assert unverified["status"] == "episode_recorded"

    add_episode(
        core,
        "criar câmera orbit no Blender",
        "passed",
        "different-context",
        3,
        context={"app": "Termux", "scene_kind": "camera_test"},
    )
    before = store.counts()

    result = core.recall_experiences(
        "criar câmera orbit no Blender",
        context=context,
        limit=5,
        min_similarity=0.4,
    )

    assert result["status"] == "completed"
    assert result["returned_count"] == 2
    assert result["verified_match_count"] == 1
    assert result["unverified_match_count"] == 1
    assert result["experiences"][0]["evidence_independently_verified"] is True
    assert result["experiences"][0]["match_type"] == "token_overlap"
    assert result["experiences"][1]["evidence_independently_verified"] is False
    assert result["experiences"][1]["confidence"] is None
    assert all(item["advisory_only"] for item in result["experiences"])
    assert all(item["execution_authorized"] is False for item in result["experiences"])
    assert result["persistent_write_performed"] is False
    assert result["semantic_consolidation_performed"] is False
    assert result["memory_modified"] is False
    assert store.counts() == before


def test_experience_recall_does_not_cross_context_or_accept_invalid_budgets(tmp_path):
    core, store = make_core(tmp_path)
    add_episode(
        core,
        "diagnosticar aquecimento do aparelho",
        "passed",
        "thermal-ci",
        1,
        context={"device": "test-device", "python": "3.14"},
    )

    wrong_context = core.cognitive.recall_experiences(
        "diagnosticar aquecimento do aparelho",
        context={"device": "desktop", "python": "3.14"},
    )
    assert wrong_context["returned_count"] == 0
    assert wrong_context["memory_modified"] is False

    with pytest.raises(ValueError, match="limit"):
        core.cognitive.recall_experiences("diagnosticar aquecimento", limit=True)
    with pytest.raises(ValueError, match="min_similarity"):
        core.cognitive.recall_experiences("diagnosticar aquecimento", min_similarity=float("nan"))
    assert store.count_events(event_type="adaptive.experience.recorded") == 1


def test_experience_recall_requires_read_authorization(tmp_path):
    core, _ = make_core(tmp_path)

    class DenyRead(Dharma):
        def evaluate(self, action, target="", context=None):
            if action == "read_project":
                return Decision(
                    allowed=False, requires_approval=True,
                    reason="Leitura bloqueada.", risk_score=60,
                    category="test", reversible=True,
                )
            return super().evaluate(action, target, context)

    core.cognitive.dharma = DenyRead(tmp_path)
    with pytest.raises(PermissionError, match="Leitura bloqueada"):
        core.recall_experiences("tarefa de teste")



def test_adaptive_status_declares_recall_limits_and_non_authority(tmp_path):
    core, _ = make_core(tmp_path)

    recall = core.cognitive.adaptive_learning.status()["experience_retrieval"]

    assert recall["supported"] is True
    assert recall["strategy"] == "exact_context_signature_plus_jaccard_token_overlap"
    assert recall["maximum_history_window"] == core.cognitive.adaptive_learning.MAX_EPISODES
    assert recall["maximum_returned_episodes"] == 20
    assert recall["read_only"] is True
    assert recall["independent_evidence_ranked_first"] is True
    assert recall["unverified_confidence_exposed"] is False
    assert recall["semantic_consolidation_performed"] is False
    assert recall["execution_authorized"] is False
