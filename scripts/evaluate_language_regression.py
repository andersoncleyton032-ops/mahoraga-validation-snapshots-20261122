"""Avalia o LanguageEngine contra um conjunto linguístico held-out.

O modo padrão é somente leitura e utiliza o modelo já existente no root.
--training-seed cria um benchmark isolado em diretório temporário; não toca
nos dados, pesos, checkpoints ou memória de produção.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.language_engine import LanguageEngine  # noqa: E402

DEFAULT_CASES = ROOT / "tests" / "fixtures" / "language_regression_v1.json"
DECISIONS = {"recognize", "abstain", "clarify", "defer"}


class ReadOnlyCognitiveSink:
    """Impede que a avaliação do modelo existente grave memória ou aprendizagem."""

    def record_observation(self, **kwargs):
        raise RuntimeError("A avaliação não pode registrar observações.")

    def record_learning(self, **kwargs):
        raise RuntimeError("A avaliação não pode registrar aprendizagem.")


class NoOpCognitiveSink:
    """Sink sem persistência para o treinamento temporário do benchmark."""

    def record_observation(self, **kwargs):
        return None

    def record_learning(self, **kwargs):
        return None


def _ratio(numerator: int, denominator: int):
    return numerator / denominator if denominator else None


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def evaluate(
    engine: LanguageEngine,
    cases: list[dict[str, Any]],
    suite_id: str = "language-regression-v1",
) -> dict[str, Any]:
    expected_actionable = 0
    predicted_actionable = 0
    correct_actionable = 0
    false_positive = 0
    false_negative = 0
    wrong_intent = 0
    safe_nonexecution = 0
    expected_nonactionable = 0
    correct_decisions = 0
    expected_counts = defaultdict(int)
    correct_counts = defaultdict(int)
    categories = defaultdict(
        lambda: {
            "total": 0,
            "correct_decisions": 0,
            "false_positive": 0,
            "false_negative": 0,
            "wrong_intent": 0,
        }
    )
    predictions = []

    for case in cases:
        expected = case["expected"]
        expected_decision = expected["decision"]
        result = engine.classify(case["text"])
        recognized = result.get("recognized") is True
        actual_decision = result.get("decision")

        if actual_decision not in DECISIONS:
            actual_decision = "recognize" if recognized else "abstain"

        actual_intent = result.get("intent")
        category = categories[case["category"]]
        category["total"] += 1
        expected_counts[expected_decision] += 1

        predicted_action = recognized and actual_decision == "recognize"
        expected_action = expected_decision == "recognize"

        if expected_action:
            expected_actionable += 1
            if predicted_action:
                predicted_actionable += 1
                if actual_intent == expected["intent"]:
                    correct_actionable += 1
                else:
                    wrong_intent += 1
                    category["wrong_intent"] += 1
            else:
                false_negative += 1
                category["false_negative"] += 1
        else:
            expected_nonactionable += 1
            if predicted_action:
                predicted_actionable += 1
                false_positive += 1
                category["false_positive"] += 1
            else:
                safe_nonexecution += 1

        exact_decision = actual_decision == expected_decision
        exact_intent = (
            expected.get("intent") is None
            or actual_intent == expected.get("intent")
        )
        exact_match = exact_decision and exact_intent
        if exact_match:
            correct_decisions += 1
            category["correct_decisions"] += 1

        correct_counts[expected_decision] += int(exact_match)

        predictions.append({
            "id": case["id"],
            "category": case["category"],
            "text": case["text"],
            "expected": expected,
            "actual": {
                "decision": actual_decision,
                "recognized": recognized,
                "intent": actual_intent,
                "reason": result.get("reason"),
                "confidence": result.get("confidence"),
                "margin": result.get("margin"),
            },
            "exact_match": exact_match,
        })

    total = len(cases)
    category_report = {}

    for name, values in sorted(categories.items()):
        category_report[name] = {
            **values,
            "accuracy": _ratio(values["correct_decisions"], values["total"]),
        }

    decision_report = {
        decision: {
            "expected": expected_counts[decision],
            "correct": correct_counts[decision],
            "accuracy": _ratio(
                correct_counts[decision], expected_counts[decision]
            ),
        }
        for decision in sorted(DECISIONS)
    }

    return {
        "suite_id": suite_id,
        "total_cases": total,
        "metrics": {
            "decision_accuracy": _ratio(correct_decisions, total),
            "action_precision": _ratio(correct_actionable, predicted_actionable),
            "action_recall": _ratio(correct_actionable, expected_actionable),
            "false_positive": false_positive,
            "false_negative": false_negative,
            "wrong_intent": wrong_intent,
            "safe_nonexecution": safe_nonexecution,
            "safe_nonexecution_rate": _ratio(
                safe_nonexecution, expected_nonactionable
            ),
            "future_action_leakage": sum(
                1 for item in predictions
                if item["expected"]["decision"] == "defer"
                and item["actual"]["decision"] == "recognize"
                and item["actual"]["recognized"]
            ),
            "expected_actionable": expected_actionable,
            "predicted_actionable": predicted_actionable,
        },
        "by_decision": decision_report,
        "by_category": category_report,
        "predictions": predictions,
        "safety_note": (
            "A avaliação chama somente LanguageEngine.classify; nenhum comando "
            "é encaminhado ou executado. Decisões defer e clarify não autorizam execução."
        ),
    }


def _load_suite(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        suite = json.load(file)

    suite_version = suite.get("version")
    if (
        isinstance(suite_version, bool)
        or not isinstance(suite_version, int)
        or suite.get("suite_id") != f"language-regression-v{suite_version}"
    ):
        raise SystemExit("Conjunto de avaliação incompatível.")
    if suite.get("split") != "held_out":
        raise SystemExit("O conjunto precisa ser marcado como held_out.")

    for case in suite.get("cases", []):
        if case.get("expected", {}).get("decision") not in DECISIONS:
            raise SystemExit(f"Decisão inválida no caso {case.get('id')}.")

    return suite


def _render_report(report: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")



def _quality_gates(evaluation: dict[str, Any], args) -> dict[str, Any]:
    """Evaluate explicit, risk-oriented thresholds without hiding raw metrics."""
    metrics = evaluation.get("metrics", {})
    specifications = (
        ("decision_accuracy", "min", args.min_decision_accuracy),
        ("action_precision", "min", args.min_action_precision),
        ("action_recall", "min", args.min_action_recall),
        ("safe_nonexecution_rate", "min", args.min_safe_nonexecution_rate),
        ("false_positive", "max", args.max_false_positives),
        ("future_action_leakage", "max", args.max_future_action_leakage),
    )
    gates = {}
    for name, direction, threshold in specifications:
        if threshold is None:
            continue
        observed = metrics.get(name)
        valid_number = (
            isinstance(observed, (int, float))
            and not isinstance(observed, bool)
        )
        passed = valid_number and (
            observed >= threshold if direction == "min"
            else observed <= threshold
        )
        gates[name] = {
            "direction": direction,
            "threshold": threshold,
            "observed": observed,
            "passed": bool(passed),
        }
    return gates

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--training-seed",
        type=Path,
        help="Treina um modelo temporário com um fixture separado e avalia o holdout.",
    )
    parser.add_argument("--epochs", type=int, default=400)
    parser.add_argument("--min-decision-accuracy", type=float)
    parser.add_argument("--min-action-precision", type=float)
    parser.add_argument("--min-action-recall", type=float)
    parser.add_argument("--min-safe-nonexecution-rate", type=float)
    parser.add_argument("--max-false-positives", type=int)
    parser.add_argument("--max-future-action-leakage", type=int)
    args = parser.parse_args()
    for name in (
        "min_decision_accuracy",
        "min_action_precision",
        "min_action_recall",
        "min_safe_nonexecution_rate",
    ):
        value = getattr(args, name)
        if value is not None and not 0 <= value <= 1:
            parser.error(f"--{name.replace('_', '-')} precisa estar entre 0 e 1.")
    for name in ("max_false_positives", "max_future_action_leakage"):
        value = getattr(args, name)
        if value is not None and value < 0:
            parser.error(f"--{name.replace('_', '-')} não pode ser negativo.")

    suite = _load_suite(args.cases)

    if args.training_seed:
        with args.training_seed.open("r", encoding="utf-8") as file:
            seed_data = json.load(file)

        seed_version = seed_data.get("version")
        if (
            isinstance(seed_version, bool)
            or not isinstance(seed_version, int)
            or seed_data.get("suite_id") != f"language-training-seed-v{seed_version}"
            or seed_data.get("split") != "training_fixture"
            or seed_data.get("not_production_data") is not True
        ):
            raise SystemExit("Fixture de treinamento incompatível ou não isolado.")

        examples = seed_data.get("examples")
        if not isinstance(examples, list) or not examples:
            raise SystemExit("Fixture de treinamento vazio ou inválido.")

        training_texts = {
            _normalize(item["text"])
            for item in examples
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        }
        holdout_texts = {
            _normalize(case["text"]) for case in suite.get("cases", [])
        }
        overlap = training_texts & holdout_texts
        if overlap:
            raise SystemExit(
                "Vazamento entre treinamento e holdout: " + repr(sorted(overlap))
            )

        with tempfile.TemporaryDirectory(
            prefix="mahoraga-language-benchmark-"
        ) as temporary_root:
            engine = LanguageEngine(
                root=Path(temporary_root),
                cognitive=NoOpCognitiveSink(),
            )
            added = engine.add_examples(
                examples,
                source="versioned_benchmark_fixture",
            )
            training = engine.train(epochs=args.epochs)
            status = engine.status()
            report = {
                "benchmark": {
                    "training_seed_id": seed_data["suite_id"],
                    "training_examples_added": added["added"],
                    "epochs_requested": args.epochs,
                    "production_data_used": False,
                    "production_model_modified": False,
                    "storage": "temporary_directory_removed_after_run",
                },
                "training": training,
                "model": status,
                "evaluation": evaluate(engine, suite["cases"], suite["suite_id"]),
            }
            report["quality_gates"] = _quality_gates(report["evaluation"], args)
            report["quality_gates_passed"] = all(
                item["passed"] for item in report["quality_gates"].values()
            )
            _render_report(report, args.output)
        return 0 if status["trained"] and report["quality_gates_passed"] else 1

    engine = LanguageEngine(
        root=args.root,
        cognitive=ReadOnlyCognitiveSink(),
    )
    status = engine.status()
    report = {
        "model": status,
        "evaluation": evaluate(engine, suite["cases"], suite["suite_id"]),
    }
    report["quality_gates"] = _quality_gates(report["evaluation"], args)
    report["quality_gates_passed"] = all(
        item["passed"] for item in report["quality_gates"].values()
    )
    _render_report(report, args.output)
    if not status["trained"]:
        return 2
    return 0 if report["quality_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
