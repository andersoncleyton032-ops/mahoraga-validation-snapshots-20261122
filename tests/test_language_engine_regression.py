"""Regressão e caracterização da avaliação linguística do Mahoraga.

Os casos em fixtures/ são holdout: nunca devem ser adicionados ao treinamento.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

import numpy as np
import pytest

from agent.language_engine import LanguageEngine, LanguageEngineError
from agent.linguistic_analysis import LinguisticAnalyzer
from scripts.evaluate_language_regression import _quality_gates


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = Path(__file__).parent / "fixtures" / "language_regression_v1.json"
CASES_V2_PATH = Path(__file__).parent / "fixtures" / "language_regression_v2.json"
CASES_V3_PATH = Path(__file__).parent / "fixtures" / "language_regression_v3.json"
TRAINING_SEED_PATH = (
    Path(__file__).parent / "fixtures" / "language_training_seed_v1.json"
)
TRAINING_SEED_V2_PATH = (
    Path(__file__).parent / "fixtures" / "language_training_seed_v2.json"
)
TRAINING_PATH = ROOT / "data" / "language_engine" / "examples.json"


@pytest.fixture(scope="module")
def evaluation_suite():
    with CASES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


class ForcedInspectionNetwork:
    """Produz uma saída controlada para testar os filtros linguísticos."""

    @staticmethod
    def predict(inputs):
        return np.tile(
            np.asarray([[0.99, 0.01]], dtype=np.float32),
            (len(inputs), 1),
        )


def _engine_forced_to_predict_inspection():
    engine = LanguageEngine.__new__(LanguageEngine)
    engine._state_lock = RLock()
    engine.ready = True
    engine.vocabulary = [
        "não", "analise", "a", "cena", "agora", "talvez", "seja",
        "bom", "olhar", "isso", "amanhã", "quero", "que", "você",
        "ontem", "eu", "inspecione", "o", "blender", "depois",
        "terminar", "verifique", "na", "próxima", "sessão",
        "confira", "objetos", "se", "pedir", "caso", "necessário",
    ]
    engine.labels = ["blender.inspect", "status"]
    engine.network = ForcedInspectionNetwork()
    engine.min_confidence = 0.60
    engine.min_margin = 0.15
    engine.linguistic = LinguisticAnalyzer()
    return engine


def test_regression_suite_declares_held_out_split(evaluation_suite):
    assert evaluation_suite["suite_id"] == "language-regression-v1"
    assert evaluation_suite["version"] == 1
    assert evaluation_suite["split"] == "held_out"
    assert "Nunca importar" in evaluation_suite["training_policy"]


def test_regression_suite_has_unique_ids_and_texts(evaluation_suite):
    cases = evaluation_suite["cases"]
    ids = [case["id"] for case in cases]
    texts = [_normalize(case["text"]) for case in cases]

    assert len(cases) >= 20
    assert len(ids) == len(set(ids))
    assert len(texts) == len(set(texts))


def test_regression_suite_covers_required_linguistic_phenomena(evaluation_suite):
    categories = {case["category"] for case in evaluation_suite["cases"]}

    assert {
        "paraphrase",
        "typo",
        "negation",
        "ambiguity",
        "future_intention",
        "past_reference",
        "conditional",
        "out_of_domain",
        "format_variation",
    } <= categories


def test_regression_case_schema_is_consistent(evaluation_suite):
    allowed_decisions = {"recognize", "abstain", "clarify", "defer"}
    allowed_intents = {"status", "blender.inspect"}

    for case in evaluation_suite["cases"]:
        assert isinstance(case["id"], str) and case["id"]
        assert isinstance(case["text"], str) and case["text"].strip()
        decision = case["expected"]["decision"]
        assert decision in allowed_decisions

        if decision in {"recognize", "defer"}:
            assert case["expected"]["intent"] in allowed_intents
        else:
            assert case["expected"]["intent"] is None



def test_regression_suite_v2_is_independent_and_covers_required_categories():
    with CASES_V2_PATH.open("r", encoding="utf-8") as file:
        suite = json.load(file)

    assert suite["suite_id"] == "language-regression-v2"
    assert suite["version"] == 2
    assert suite["split"] == "held_out"

    ids = [case["id"] for case in suite["cases"]]
    texts = [_normalize(case["text"]) for case in suite["cases"]]
    categories = {case["category"] for case in suite["cases"]}

    assert len(suite["cases"]) >= 35
    assert len(ids) == len(set(ids))
    assert len(texts) == len(set(texts))
    assert {
        "paraphrase", "typo", "negation", "ambiguity",
        "future_intention", "past_reference", "conditional",
        "out_of_domain", "format_variation",
    } <= categories

    with TRAINING_SEED_V2_PATH.open("r", encoding="utf-8") as file:
        training = json.load(file)
    training_texts = {
        _normalize(item["text"]) for item in training["examples"]
    }
    assert not (training_texts & set(texts))

def test_training_seed_is_versioned_and_disjoint_from_holdout(evaluation_suite):
    with TRAINING_SEED_PATH.open("r", encoding="utf-8") as file:
        seed = json.load(file)

    assert seed["suite_id"] == "language-training-seed-v1"
    assert seed["version"] == 1
    assert seed["split"] == "training_fixture"
    assert seed["not_production_data"] is True

    examples = seed["examples"]
    training_texts = [_normalize(item["text"]) for item in examples]
    holdout_texts = {
        _normalize(case["text"]) for case in evaluation_suite["cases"]
    }

    assert len(examples) >= 20
    assert len(training_texts) == len(set(training_texts))
    assert not (set(training_texts) & holdout_texts)
    assert {item["intent"] for item in examples} == {
        "status", "blender.inspect"
    }



def test_training_seed_v2_is_expanded_and_disjoint_from_holdout(evaluation_suite):
    with TRAINING_SEED_V2_PATH.open("r", encoding="utf-8") as file:
        seed = json.load(file)

    assert seed["suite_id"] == "language-training-seed-v2"
    assert seed["version"] == 2
    assert seed["split"] == "training_fixture"
    assert seed["not_production_data"] is True
    assert seed["derived_from"] == "language-training-seed-v1"

    examples = seed["examples"]
    training_texts = [_normalize(item["text"]) for item in examples]
    holdout_texts = {
        _normalize(case["text"]) for case in evaluation_suite["cases"]
    }

    assert len(examples) == 40
    assert len(training_texts) == len(set(training_texts))
    assert not (set(training_texts) & holdout_texts)
    assert {item["intent"] for item in examples} == {
        "status", "blender.inspect"
    }

def test_holdout_cases_do_not_duplicate_local_training_examples_when_available(
    evaluation_suite,
):
    if not TRAINING_PATH.exists():
        pytest.skip("Conjunto local de treinamento não está disponível neste ambiente.")

    with TRAINING_PATH.open("r", encoding="utf-8") as file:
        training_data = json.load(file)

    training_texts = {
        _normalize(item["text"])
        for item in training_data.get("examples", [])
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    }
    holdout_texts = {
        _normalize(case["text"])
        for case in evaluation_suite["cases"]
    }

    overlap = training_texts & holdout_texts
    assert not overlap, f"Vazamento entre treinamento e avaliação: {sorted(overlap)}"


def test_tokenizer_preserves_negation_as_a_token():
    tokens = LanguageEngine._tokens("NÃO analise a cena")

    assert "não" in tokens
    assert "analise" in tokens
    assert "cena" in tokens


def test_legacy_bag_of_words_loses_unseen_negation_signal():
    """Caracteriza a limitação histórica do vocabulário sem o token de negação."""
    engine = LanguageEngine.__new__(LanguageEngine)
    engine.vocabulary = ["analise", "a", "cena"]
    engine.linguistic = LinguisticAnalyzer()

    positive = engine._features(["analise a cena"])
    negative = engine._features(["não analise a cena"])

    assert np.array_equal(positive, negative)


def test_legacy_vectorizer_rejects_text_with_only_unknown_tokens():
    engine = LanguageEngine.__new__(LanguageEngine)
    engine.vocabulary = ["status", "sistema"]
    engine.linguistic = LinguisticAnalyzer()

    vector = engine._features(["previsão meteorológica"])

    assert vector.shape == (1, 2)
    assert not np.any(vector)


def test_linguistic_aliases_project_to_existing_features():
    engine = LanguageEngine.__new__(LanguageEngine)
    engine.vocabulary = [
        "estado", "plataforma", "funcionamento", "cena", "objetos",
        "condição", "serviços"
    ]
    engine.linguistic = LinguisticAnalyzer()

    vector = engine._features([
        "STATUS sistema funcionando Blender carregado condiçao servicos"
    ])

    assert vector.shape == (1, 7)
    assert np.all(vector == 1.0)


def test_negated_inspection_is_not_recognized_as_an_action():
    result = _engine_forced_to_predict_inspection().classify(
        "Não analise a cena agora."
    )

    assert result["recognized"] is False
    assert result["decision"] == "abstain"
    assert result["reason"] == "negated_action"


def test_ambiguous_reference_requests_clarification():
    result = _engine_forced_to_predict_inspection().classify(
        "Talvez seja bom olhar isso."
    )

    assert result["recognized"] is False
    assert result["decision"] == "clarify"


def test_future_inspection_is_deferred_not_executed():
    result = _engine_forced_to_predict_inspection().classify(
        "Amanhã quero que você analise a cena."
    )

    assert result["recognized"] is False
    assert result["decision"] == "defer"
    assert result.get("intent") == "blender.inspect"


def test_past_inspection_reference_is_not_actionable():
    result = _engine_forced_to_predict_inspection().classify(
        "Ontem eu analisei a cena do Blender."
    )

    assert result["recognized"] is False
    assert result["decision"] == "abstain"
    assert result["reason"] == "past_reference"


def test_regression_suite_v3_is_independent_and_polysemy_focused():
    with CASES_V3_PATH.open("r", encoding="utf-8") as file:
        suite = json.load(file)

    assert suite["suite_id"] == "language-regression-v3"
    assert suite["version"] == 3
    assert suite["split"] == "held_out"
    assert len(suite["cases"]) >= 40

    ids = [case["id"] for case in suite["cases"]]
    texts = [_normalize(case["text"]) for case in suite["cases"]]
    categories = {case["category"] for case in suite["cases"]}
    assert len(ids) == len(set(ids))
    assert len(texts) == len(set(texts))
    assert {"out_of_domain", "past_reference"} <= categories

    with TRAINING_SEED_V2_PATH.open("r", encoding="utf-8") as file:
        training = json.load(file)
    training_texts = {
        _normalize(item["text"]) for item in training["examples"]
    }
    with CASES_V2_PATH.open("r", encoding="utf-8") as file:
        previous_suite = json.load(file)
    previous_texts = {
        _normalize(case["text"]) for case in previous_suite["cases"]
    }
    assert not (training_texts & set(texts))
    assert not (previous_texts & set(texts))

    for case in suite["cases"]:
        assert case["expected"] == {"decision": "abstain", "intent": None}


def test_polysemous_out_of_domain_text_never_reaches_neural_classifier():
    engine = _engine_forced_to_predict_inspection()
    phrases = [
        "Como está o sistema solar?",
        "Explique o processo de fotossíntese.",
        "Quais recursos naturais existem na Amazônia?",
        "Qual é a situação política do país?",
        "Explique o modelo matemático de crescimento.",
        "Analise a estrutura do texto.",
    ]
    for text in phrases:
        result = engine.classify(text)
        assert result["recognized"] is False
        assert result["decision"] == "abstain"
        assert result["reason"] == "unsupported_domain"


def test_past_reference_with_unlisted_verbs_never_reaches_neural_classifier():
    engine = _engine_forced_to_predict_inspection()
    phrases = [
        "Ontem o sistema apresentou erro.",
        "O relatório foi concluído ontem.",
        "Mais cedo os serviços ficaram indisponíveis.",
        "Na sessão anterior o núcleo permaneceu estável.",
    ]
    for text in phrases:
        result = engine.classify(text)
        assert result["recognized"] is False
        assert result["decision"] == "abstain"
        assert result["reason"] == "past_reference"


def test_future_generic_object_target_is_deferred_without_recognition():
    result = _engine_forced_to_predict_inspection().classify(
        "Na próxima sessão, confira os objetos."
    )
    assert result["recognized"] is False
    assert result["decision"] == "defer"
    assert result["intent"] == "blender.inspect"


class FakeLanguageCognitive:
    def record_observation(self, **kwargs):
        return {"status": "recorded"}

    def record_learning(self, **kwargs):
        return {"status": "recorded"}



def test_language_prediction_exposes_checkpoint_scoped_predictor_identity():
    engine = _engine_forced_to_predict_inspection()
    engine.predictor_id = "language-engine:0123456789abcdef01234567"
    engine.linguistic.analyze = lambda text: {"decision": "recognize", "reason": None}

    result = engine.classify("inspecione a cena do Blender")

    assert result["recognized"] is True
    assert result["candidate_intent"] == "blender.inspect"
    assert result["predictor_id"] == engine.predictor_id
    assert result["confidence_target"] == "candidate_intent"


def test_language_domain_anchor_confidence_remains_scoped_to_neural_candidate():
    engine = _engine_forced_to_predict_inspection()
    engine.predictor_id = "language-engine:0123456789abcdef01234567"
    engine.linguistic.analyze = lambda text: {
        "decision": "defer",
        "reason": "future_reference",
    }
    engine.linguistic.infer_intent_hint = lambda text: "status"

    result = engine.classify("amanhã confira o sistema")

    assert result["decision"] == "defer"
    assert result["intent"] == "status"
    assert result["candidate_intent"] == "blender.inspect"
    assert result["confidence_target"] == "candidate_intent"
    assert result["predictor_id"] == engine.predictor_id


def test_language_predictor_id_changes_when_checkpoint_bytes_change(tmp_path):
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())
    engine.base.mkdir(parents=True, exist_ok=True)
    engine.model_path.write_bytes(b"checkpoint-a")
    architecture = {"layers": [8, 2]}

    first = engine._predictor_id_for_checkpoint(architecture)
    repeated = engine._predictor_id_for_checkpoint(architecture)
    engine.model_path.write_bytes(b"checkpoint-b")
    changed = engine._predictor_id_for_checkpoint(architecture)

    assert first == repeated
    assert first != changed
    assert first.startswith("language-engine:")


def test_add_examples_deduplicates_repeated_normalized_pairs(tmp_path):
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())
    result = engine.add_examples([
        {"text": "  STATUS   do sistema ", "intent": "status"},
        {"text": "status do sistema", "intent": "STATUS"},
        {"text": "Status do sistema", "intent": "status"},
    ], source="unit-test")

    assert result["added"] == 1
    assert result["provenance_added"] == 1
    assert len(engine.examples) == 1
    assert len(engine.provenance_records) == 1
    assert engine.provenance_records[0]["source_label"] == "unit-test"
    assert engine.provenance_records[0]["trust_state"] == "caller_declared_unverified"


def test_add_examples_rejects_conflicting_labels_for_same_normalized_text(tmp_path):
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())

    with pytest.raises(ValueError, match="intenções diferentes"):
        engine.add_examples([
            {"text": "Status do sistema", "intent": "status"},
            {"text": " status   do sistema ", "intent": "blender.inspect"},
        ], source="unit-test")

    assert engine.examples == []


def test_load_examples_rejects_non_object_json_root(tmp_path):
    base = tmp_path / "data" / "language_engine"
    base.mkdir(parents=True)
    (base / "examples.json").write_text("[]", encoding="utf-8")

    with pytest.raises(LanguageEngineError, match="Raiz do conjunto de exemplos"):
        LanguageEngine(tmp_path, FakeLanguageCognitive())


def test_load_examples_deduplicates_legacy_exact_pairs(tmp_path):
    base = tmp_path / "data" / "language_engine"
    base.mkdir(parents=True)
    (base / "examples.json").write_text(json.dumps({
        "version": LanguageEngine.VERSION,
        "examples": [
            {"text": "Status do sistema", "intent": "status"},
            {"text": " status   do sistema ", "intent": "STATUS"},
        ],
    }), encoding="utf-8")

    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())

    assert engine.examples == [{"text": "status do sistema", "intent": "status"}]


def test_duplicate_example_from_new_source_adds_lineage_without_retraining_sample(tmp_path):
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())
    example = {"text": "Mostre o estado do sistema", "intent": "status"}
    first = engine.add_examples([example], source="source-a")
    second = engine.add_examples([example], source="source-b")

    assert first["added"] == 1
    assert second["status"] == "provenance_updated"
    assert second["added"] == 0
    assert second["provenance_added"] == 1
    assert len(engine.examples) == 1
    assert {item["source_label"] for item in engine.provenance_records} == {"source-a", "source-b"}
    assert all(item["trust_state"] == "caller_declared_unverified" for item in engine.provenance_records)


def test_repeating_same_source_does_not_duplicate_provenance(tmp_path):
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())
    example = {"text": "Mostre o estado do sistema", "intent": "status"}
    engine.add_examples([example], source="source-a")
    result = engine.add_examples([example], source="source-a")

    assert result == {"status": "unchanged", "added": 0}
    assert len(engine.provenance_records) == 1


def test_legacy_examples_get_unknown_provenance_without_rewriting_file(tmp_path):
    base = tmp_path / "data" / "language_engine"
    base.mkdir(parents=True)
    path = base / "examples.json"
    original = json.dumps({
        "version": LanguageEngine.VERSION,
        "examples": [{"text": "Status do sistema", "intent": "status"}],
    })
    path.write_text(original, encoding="utf-8")
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())

    assert path.read_text(encoding="utf-8") == original
    assert engine.provenance_records == [{
        "example_id": engine._example_id(engine.examples[0]),
        "source_label": None,
        "recorded_at": None,
        "record_id": None,
        "trust_state": "legacy_source_unknown",
    }]


def test_loader_rejects_examples_without_provenance_records(tmp_path):
    base = tmp_path / "data" / "language_engine"
    base.mkdir(parents=True)
    (base / "examples.json").write_text(json.dumps({
        "version": LanguageEngine.VERSION,
        "examples": [{"text": "Status do sistema", "intent": "status"}],
        "provenance_schema_version": 1,
        "provenance": [],
    }), encoding="utf-8")
    with pytest.raises(LanguageEngineError, match="exemplos sem registro"):
        LanguageEngine(tmp_path, FakeLanguageCognitive())


def test_model_loader_rejects_non_object_metadata_without_crashing(tmp_path):
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())
    engine.base.mkdir(parents=True, exist_ok=True)
    engine.model_path.write_bytes(b"not-a-model")
    engine.metadata_path.write_text("[]", encoding="utf-8")

    assert engine._load_model() is False
    assert engine.ready is False


def test_model_loader_rejects_legacy_unversioned_feature_contract(tmp_path):
    engine = LanguageEngine(tmp_path, FakeLanguageCognitive())
    engine.base.mkdir(parents=True, exist_ok=True)
    engine.model_path.write_bytes(b"not-a-model")
    engine.metadata_path.write_text(json.dumps({
        "version": LanguageEngine.VERSION,
        "vocabulary": ["status", "sistema"],
        "labels": ["status", "blender.inspect"],
        "examples": 0,
        "dataset_sha256": engine._dataset_sha256(),
        "architecture": {},
    }), encoding="utf-8")

    assert engine._load_model() is False
    assert engine.ready is False


def test_loader_rejects_boolean_provenance_schema_version(tmp_path):
    base = tmp_path / "data" / "language_engine"
    base.mkdir(parents=True)
    example = {"text": "Status do sistema", "intent": "status"}
    example_id = LanguageEngine._example_id({
        "text": "status do sistema",
        "intent": "status",
    })
    record = {
        "example_id": example_id,
        "source_label": "fixture",
        "recorded_at": "2026-11-18T00:00:00+00:00",
        "record_id": "a" * 32,
        "trust_state": "caller_declared_unverified",
    }
    (base / "examples.json").write_text(json.dumps({
        "version": LanguageEngine.VERSION,
        "examples": [example],
        "provenance_schema_version": True,
        "provenance": [record],
    }), encoding="utf-8")

    with pytest.raises(LanguageEngineError, match="Versão do esquema"):
        LanguageEngine(tmp_path, FakeLanguageCognitive())



def test_language_quality_gates_enforce_precision_recall_and_safe_abstention():
    class Thresholds:
        min_decision_accuracy = 0.95
        min_action_precision = 0.95
        min_action_recall = 0.80
        min_safe_nonexecution_rate = 0.95
        max_false_positives = 0
        max_future_action_leakage = 0

    passing = _quality_gates({
        "metrics": {
            "decision_accuracy": 0.963,
            "action_precision": 1.0,
            "action_recall": 0.909,
            "safe_nonexecution_rate": 1.0,
            "false_positive": 0,
            "future_action_leakage": 0,
        }
    }, Thresholds())
    assert all(item["passed"] for item in passing.values())


def test_language_quality_gates_reject_safety_regressions_and_missing_metrics():
    class Thresholds:
        min_decision_accuracy = 0.95
        min_action_precision = 0.95
        min_action_recall = 0.80
        min_safe_nonexecution_rate = 0.95
        max_false_positives = 0
        max_future_action_leakage = 0

    failing = _quality_gates({
        "metrics": {
            "decision_accuracy": 0.90,
            "action_precision": 0.80,
            "action_recall": 0.85,
            "safe_nonexecution_rate": 0.90,
            "false_positive": 1,
            "future_action_leakage": 1,
        }
    }, Thresholds())
    assert not all(item["passed"] for item in failing.values())
    assert failing["false_positive"]["passed"] is False
    assert failing["future_action_leakage"]["passed"] is False

    missing = _quality_gates({"metrics": {}}, Thresholds())
    assert all(item["passed"] is False for item in missing.values())
