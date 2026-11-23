import json
from pathlib import Path

import pytest

from scripts.evaluate_knowledge_retrieval import (
    evaluate_suite,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_precision_recall_and_reciprocal_rank_metrics():
    retrieved = ["alpha", "beta", "gamma"]
    relevant = {"beta"}

    assert precision_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)
    assert recall_at_k(retrieved, relevant, 3) == 1.0
    assert reciprocal_rank(retrieved, relevant) == 0.5


def test_metrics_reject_invalid_k_and_empty_relevance():
    with pytest.raises(ValueError):
        precision_at_k(["alpha"], {"alpha"}, 0)

    with pytest.raises(ValueError):
        recall_at_k(["alpha"], set(), 3)

    with pytest.raises(ValueError):
        reciprocal_rank([], set())


def test_held_out_suite_establishes_lexical_baseline():
    suite = Path("tests/fixtures/knowledge_retrieval_v1.json")
    report = evaluate_suite(suite, k=3)

    assert report["split"] == "held_out"
    assert report["training_performed"] is False
    assert report["storage"] == "temporary_sqlite_discarded_after_evaluation"
    assert report["corpus_documents"] == 10
    assert report["query_count"] == 14
    assert report["by_category"]["lexical"]["recall_at_k"] == 1.0
    assert report["by_category"]["lexical"]["mrr"] == 1.0
    assert report["by_category"]["semantic_gap"]["recall_at_k"] < 1.0
    assert report["by_category"]["typo"]["recall_at_k"] == 0.0


def test_held_out_evaluation_is_deterministic():
    suite = Path("tests/fixtures/knowledge_retrieval_v1.json")
    first = evaluate_suite(suite, k=3)
    second = evaluate_suite(suite, k=3)

    assert first == second


def test_evaluator_rejects_training_split(tmp_path):
    suite = {
        "suite_id": "invalid",
        "version": 1,
        "split": "training",
        "corpus": [{"id": "one", "subject": "test", "text": "sample"}],
        "queries": [{
            "id": "q1",
            "category": "lexical",
            "query": "sample",
            "relevant_document_ids": ["one"],
        }],
    }
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(suite), encoding="utf-8")

    with pytest.raises(ValueError, match="held_out"):
        evaluate_suite(path)
