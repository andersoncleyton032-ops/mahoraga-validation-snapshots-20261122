from __future__ import annotations

from scripts.evaluate_prototype_plasticity import run_benchmark


def test_prototype_plasticity_benchmark_passes_all_synthetic_gates():
    result = run_benchmark()

    assert result["schema"] == "mahoraga.prototype_plasticity_evaluation"
    assert result["dataset_version"] == "prototype-plasticity-synthetic-v1"
    assert result["evaluation_scope"] == "synthetic_feature_vectors_only"
    assert result["persistence_scope"] == "disposable_in_memory_append_only_store"
    assert result["all_gates_passed"] is True
    assert all(result["gates"].values())


def test_benchmark_measures_adaptation_without_forgetting_old_classes():
    metrics = run_benchmark()["metrics"]

    assert metrics["old_classes_before_adaptation"]["accuracy"] == 1.0
    assert metrics["old_classes_after_adaptation"]["accuracy"] == 1.0
    assert metrics["new_class_before_adaptation"]["accuracy"] == 0.0
    assert metrics["new_class_after_adaptation"]["accuracy"] == 1.0
    assert metrics["retention_loss"] == 0.0
    assert metrics["new_class_accuracy_gain"] == 1.0


def test_benchmark_checks_ambiguity_novelty_and_append_only_replay():
    metrics = run_benchmark()["metrics"]

    assert metrics["ambiguous_before_adaptation"]["abstained"] is True
    assert metrics["novel_class_after_adaptation"]["novel_decisions"] == 1
    assert metrics["replay"]["old_classes_accuracy"] == 1.0
    assert metrics["replay"]["new_class_accuracy"] == 1.0
    assert metrics["replay"]["novel_class_rejections"] == 1


def test_benchmark_metrics_are_deterministic():
    first = run_benchmark()
    second = run_benchmark()

    assert first["metrics"] == second["metrics"]
    assert first["gates"] == second["gates"]
