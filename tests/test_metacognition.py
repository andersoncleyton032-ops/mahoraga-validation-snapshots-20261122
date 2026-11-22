import pytest

from agent.cognitive_engine import CognitiveEngine
from agent.store import KnowledgeStore


class FakeEvidenceVerifier:
    def verify_attestation(self, *, attestation, action, subject_sha256, source):
        if attestation != "trusted-test-attestation":
            return None
        return {
            "verified": True,
            "subject_sha256": subject_sha256,
            "source_identity_verified": True,
            "source_id": "test-sensor",
            "verifier_id": "test-verifier",
            "receipt_id": f"receipt-{subject_sha256[:12]}",
        }

    def verify_receipt(self, *, receipt, action, subject_sha256):
        return (
            action == "adaptive.record_experience"
            and isinstance(receipt, dict)
            and receipt.get("verified") is True
            and receipt.get("subject_sha256") == subject_sha256
            and receipt.get("source_identity_verified") is True
        )


@pytest.fixture
def engine(tmp_path):
    return CognitiveEngine(
        store=KnowledgeStore(tmp_path / "metacognition.sqlite3"),
        evidence_verifier=FakeEvidenceVerifier(),
    )


def record_binary_episode(engine, index, correct=True, attested=True, predictor_id="language-intent-v1", confidence=0.9):
    engine.record_experience(
        task="language intent classification",
        action=f"classify sample {index}",
        outcome="positive" if correct else "negative",
        expected_outcome="positive",
        source="test_sensor",
        confidence=confidence,
        references={"predictor_id": predictor_id},
        evidence_attestation=(
            "trusted-test-attestation" if attested else None
        ),
    )


def test_metacognition_uses_only_verified_episodes_and_predictor_scope(engine):
    for index in range(10):
        record_binary_episode(engine, index, correct=True)
    for index in range(10, 20):
        record_binary_episode(engine, index, correct=False)
    record_binary_episode(engine, 21, correct=True, attested=False)
    record_binary_episode(engine, 22, correct=True, predictor_id="other-model")

    report = engine.metacognition.report(
        task="language intent classification",
        predictor_id="language-intent-v1",
    )

    assert report["status"] == "available"
    assert report["categorical_prediction_count"] == 20
    assert report["unverified_episodes_excluded"] == 1
    assert report["brier_score"] == pytest.approx(0.41)
    assert report["expected_calibration_error"] == pytest.approx(0.4)


def test_conflicting_predictor_identities_are_excluded(engine):
    engine.record_experience(
        task="numeric sensor prediction",
        action="predict sensor value",
        outcome="observed",
        source="test_sensor",
        prediction=[1.0],
        observed=[1.1],
        prediction_scale=1.0,
        prediction_metric="normalized_mae",
        predictor_id="model-a",
        references={"predictor_id": "model-b"},
        evidence_attestation="trusted-test-attestation",
    )

    report = engine.metacognition.report(predictor_id="model-a")

    assert report["numeric_prediction_count"] == 0
    assert report["predictor_identity_conflicts_excluded"] == 1


def test_unscoped_report_does_not_mix_predictors(engine):
    record_binary_episode(engine, 1, predictor_id="model-a")
    record_binary_episode(engine, 2, predictor_id="model-b")

    report = engine.metacognition.report()

    assert report["status"] == "predictor_scope_required"
    assert report["brier_score"] is None
    assert set(report["by_scope"]) == {"model-a", "model-b"}
    assert set(report["by_scope"]["model-a"]) == {"language intent classification"}


def test_metacognitive_assessment_abstains_when_calibration_is_poor(engine):
    for index in range(20):
        record_binary_episode(engine, index, correct=index < 10)

    result = engine.assess_confidence(
        0.9,
        task="language intent classification",
        predictor_id="language-intent-v1",
        minimum_samples=20,
        maximum_ece=0.15,
    )

    assert result["decision"] == "abstain"
    assert result["abstain"] is True
    assert result["execution_authorized"] is False
    assert result["calibration"]["expected_calibration_error"] == pytest.approx(0.4)


def test_metacognitive_assessment_abstains_without_verified_calibration(engine):
    record_binary_episode(engine, 1, attested=False)

    result = engine.assess_confidence(
        0.99, predictor_id="language-intent-v1", minimum_samples=1
    )

    assert result["decision"] == "abstain"
    assert "amostra verificada insuficiente para calibrar esta decisão" in result["reasons"]


def test_metacognition_requires_predictor_and_task_scope_for_assessment(engine):
    result = engine.assess_confidence(0.99, minimum_samples=1)

    assert result["decision"] == "abstain"
    assert "predictor_id é obrigatório para evitar misturar modelos" in result["reasons"]
    assert "task é obrigatório para evitar misturar domínios" in result["reasons"]


def test_well_calibrated_predictor_can_pass_advisory_assessment(engine):
    for index in range(20):
        record_binary_episode(engine, index, correct=True)

    result = engine.assess_confidence(
        0.9,
        task="language intent classification",
        predictor_id="language-intent-v1",
        minimum_samples=20,
        maximum_ece=0.15,
    )

    assert result["decision"] == "proceed_with_caution"
    assert result["abstain"] is False
    assert result["execution_authorized"] is False



def test_report_requires_task_scope_before_aggregating_predictor(engine):
    for index in range(20):
        record_binary_episode(engine, index, correct=True, predictor_id="model-a")
    for index in range(20, 40):
        engine.record_experience(
            task="sentiment classification",
            action=f"classify sentiment {index}",
            outcome="negative",
            expected_outcome="positive",
            source="test_sensor",
            confidence=0.9,
            references={"predictor_id": "model-a"},
            evidence_attestation="trusted-test-attestation",
        )

    report = engine.metacognition.report(predictor_id="model-a")

    assert report["status"] == "task_scope_required"
    assert report["brier_score"] is None
    assert report["categorical_prediction_count"] == 0
    assert set(report["by_task"]) == {
        "language intent classification",
        "sentiment classification",
    }


def test_report_requires_predictor_scope_before_aggregating_task(engine):
    for index in range(20):
        record_binary_episode(engine, index, correct=True, predictor_id="model-a")
    for index in range(20, 40):
        record_binary_episode(engine, index, correct=False, predictor_id="model-b")

    report = engine.metacognition.report(task="language intent classification")

    assert report["status"] == "predictor_scope_required"
    assert report["brier_score"] is None
    assert report["categorical_prediction_count"] == 0
    assert set(report["by_predictor"]) == {"model-a", "model-b"}


def test_numeric_errors_are_not_aggregated_across_tasks(engine):
    for task, predicted in (
        ("sensor temperature", 1.0),
        ("sensor pressure", 2.0),
    ):
        engine.record_experience(
            task=task,
            action="predict sensor",
            outcome="observed",
            source="test_sensor",
            prediction=[predicted],
            observed=[predicted + 0.1],
            prediction_scale=1.0,
            prediction_metric="normalized_mae",
            predictor_id="sensor-model-v1",
            evidence_attestation="trusted-test-attestation",
        )

    report = engine.metacognition.report(predictor_id="sensor-model-v1")

    assert report["status"] == "task_scope_required"
    assert report["mean_normalized_numeric_error"] is None
    assert set(report["numeric_error_by_scope"]["sensor-model-v1"]) == {
        "sensor temperature",
        "sensor pressure",
    }



def test_assessment_checks_the_current_confidence_bin_not_only_global_ece(engine):
    # The low-confidence bin is calibrated (9/90 correct at 0.1).
    for index in range(90):
        record_binary_episode(
            engine,
            index,
            correct=index < 9,
            confidence=0.1,
        )
    # The high-confidence bin is badly miscalibrated (0/10 correct at 0.9).
    for index in range(90, 100):
        record_binary_episode(
            engine,
            index,
            correct=False,
            confidence=0.9,
        )

    result = engine.assess_confidence(
        0.9,
        task="language intent classification",
        predictor_id="language-intent-v1",
        minimum_samples=20,
        minimum_bin_samples=5,
        maximum_ece=0.15,
    )

    assert result["calibration"]["expected_calibration_error"] == pytest.approx(0.09)
    assert result["calibration_bin"]["count"] == 10
    assert result["calibration_bin_error"] == pytest.approx(0.9)
    assert result["decision"] == "abstain"
    assert "calibração inadequada no intervalo da confiança atual" in result["reasons"]


def test_assessment_abstains_when_current_confidence_bin_is_sparse(engine):
    for index in range(20):
        record_binary_episode(engine, index, correct=True, confidence=0.5)

    result = engine.assess_confidence(
        0.9,
        task="language intent classification",
        predictor_id="language-intent-v1",
        minimum_samples=20,
        minimum_bin_samples=5,
    )

    assert result["decision"] == "abstain"
    assert "amostra insuficiente no intervalo da confiança atual" in result["reasons"]


def test_metacognition_rejects_invalid_inputs(engine):
    for confidence in (True, -0.1, 1.1, float("nan"), "0.8", 10 ** 1000):
        with pytest.raises(ValueError):
            engine.assess_confidence(confidence)
    with pytest.raises(ValueError):
        engine.metacognition.report(bins=1)
    with pytest.raises(ValueError):
        engine.metacognition.report(limit=1001)


def test_cognitive_status_exposes_metacognition(engine):
    status = engine.status()
    assert status["metacognition"]["component"] == "MetacognitiveMonitor"
    assert status["metacognition"]["status"] == "not_assessed"
    assert status["metacognition"]["calibration_computed"] is False


def test_metacognition_status_does_not_verify_episode_evidence(engine):
    record_binary_episode(engine, 1, correct=True)
    verifier = engine.evidence_verifier
    calls = []
    original = verifier.verify_receipt

    def tracked_verify_receipt(*, receipt, action, subject_sha256):
        calls.append(subject_sha256)
        return original(
            receipt=receipt,
            action=action,
            subject_sha256=subject_sha256,
        )

    verifier.verify_receipt = tracked_verify_receipt
    status = engine.metacognition.status()

    assert status["status"] == "not_assessed"
    assert status["episodes_recorded"] == 1
    assert status["evidence_verification_checks"] == 0
    assert calls == []


def test_scoped_report_filters_before_expensive_evidence_verification(engine):
    record_binary_episode(engine, 1, correct=True, predictor_id="language-intent-v1")
    record_binary_episode(engine, 2, correct=True, predictor_id="other-model")
    record_binary_episode(engine, 3, correct=True, attested=False, predictor_id="language-intent-v1")
    engine.record_experience(
        task="numeric sensor prediction",
        action="predict sensor value",
        outcome="observed",
        source="test_sensor",
        expected_outcome="observed",
        confidence=0.9,
        references={"predictor_id": "language-intent-v1"},
        evidence_attestation="trusted-test-attestation",
    )

    verifier = engine.evidence_verifier
    original_verify_receipt = verifier.verify_receipt
    verified_subjects = []

    def tracked_verify_receipt(*, receipt, action, subject_sha256):
        verified_subjects.append(subject_sha256)
        return original_verify_receipt(
            receipt=receipt,
            action=action,
            subject_sha256=subject_sha256,
        )

    verifier.verify_receipt = tracked_verify_receipt
    report = engine.metacognition.report(
        task="language intent classification",
        predictor_id="language-intent-v1",
    )

    assert len(verified_subjects) == 1
    assert report["evidence_verification_checks"] == 2
    assert report["out_of_scope_predictor_episodes"] == 1
    assert report["out_of_scope_task_episodes"] == 1
    assert report["unverified_episodes_excluded"] == 1
    assert report["independently_verified_episodes"] == 1
    assert report["categorical_prediction_count"] == 1


def test_report_marks_bounded_history_as_truncated(engine):
    record_binary_episode(engine, 1, correct=True)
    record_binary_episode(engine, 2, correct=True)

    report = engine.metacognition.report(
        limit=1,
        task="language intent classification",
        predictor_id="language-intent-v1",
    )

    assert report["episodes_examined"] == 1
    assert report["total_recorded_episodes"] == 2
    assert report["window_limit"] == 1
    assert report["window_truncated"] is True


def test_report_marks_history_complete_when_all_events_fit(engine):
    record_binary_episode(engine, 1, correct=True)

    report = engine.metacognition.report(
        limit=1,
        task="language intent classification",
        predictor_id="language-intent-v1",
    )

    assert report["episodes_examined"] == 1
    assert report["total_recorded_episodes"] == 1
    assert report["window_truncated"] is False


def test_assessment_abstains_when_recorded_history_exceeds_window(engine):
    for index in range(20):
        record_binary_episode(engine, index, correct=True, confidence=0.9)

    original_count_events = engine.store.count_events

    def count_events_with_older_history(event_type=None):
        total = original_count_events(event_type=event_type)
        if event_type == engine.metacognition.EVENT_TYPE:
            return total + 1
        return total

    engine.store.count_events = count_events_with_older_history

    result = engine.assess_confidence(
        0.9,
        task="language intent classification",
        predictor_id="language-intent-v1",
        minimum_samples=20,
        minimum_bin_samples=5,
        maximum_ece=0.15,
    )

    assert result["decision"] == "abstain"
    assert result["abstain"] is True
    assert (
        "histórico truncado: a avaliação não cobre todos os episódios registrados"
        in result["reasons"]
    )
    assert result["calibration"]["window_truncated"] is True
    assert result["execution_authorized"] is False

