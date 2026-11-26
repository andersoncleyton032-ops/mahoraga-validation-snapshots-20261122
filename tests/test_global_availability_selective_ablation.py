import json
import subprocess
import sys
from pathlib import Path

import pytest

from experiments.global_availability_selective_ablation import (
    DOMAINS,
    run_experiment,
)


def _conditions(report):
    return {item["condition_id"]: item for item in report["conditions"]}


def test_targeted_baseline_topic_broadcast_and_global_broadcast_are_distinct():
    report = run_experiment()
    conditions = _conditions(report)

    assert report["status"] == "passed"
    assert conditions["targeted_baseline"]["observed_domains"] == ["report"]
    assert conditions["topic_subset_broadcast"]["observed_domains"] == [
        "report",
        "memory",
    ]
    assert conditions["declared_global_broadcast"]["observed_domains"] == list(DOMAINS)
    assert conditions["declared_global_broadcast"]["signal_count"] == 2
    assert conditions["declared_global_broadcast"]["distractor_state_id_recorded"] is False


@pytest.mark.parametrize("ablated_domain", DOMAINS)
def test_selective_subscriber_ablation_produces_only_the_predicted_deficit(ablated_domain):
    report = run_experiment()
    case = _conditions(report)[f"subscriber_ablation:{ablated_domain}"]

    assert case["ablated_domain"] == ablated_domain
    assert case["missing_domains"] == [ablated_domain]
    assert case["unexpected_domains"] == []
    assert len(case["observed_domains"]) == len(DOMAINS) - 1
    assert case["selective_deficit"] is True
    assert case["passed"] is True


def test_same_opaque_state_id_is_used_across_all_conditions():
    report = run_experiment()
    state_ids = {item["state_id"] for item in report["conditions"]}

    assert report["state_id"].startswith("state-")
    assert state_ids == {report["state_id"]}
    for condition in report["conditions"]:
        for receipt in condition["receipts"].values():
            assert receipt["state_id"] == report["state_id"]


def test_irrelevant_control_signal_is_not_misattributed_to_the_shared_state():
    report = run_experiment()
    control = _conditions(report)["declared_global_broadcast"]

    assert control["distractor_injected"] is True
    assert control["distractor_state_id_recorded"] is False
    assert control["observed_domains"] == list(DOMAINS)


def test_experiment_replay_is_deterministic_and_side_effect_free():
    first = run_experiment("fixed-seed")
    second = run_experiment("fixed-seed")

    assert first == second
    assert first["report_sha256"]
    assert first["execution_performed"] is False
    assert first["persistent_writes"] is False
    assert first["external_actions"] is False
    assert first["phenomenal_consciousness_inference"] == "not_measured_not_inferred"


def test_report_does_not_claim_universal_broadcast_or_phenomenal_evidence():
    report = run_experiment()

    assert any("not a universal broadcast" in item for item in report["limitations"])
    assert any("does not establish subjective" in item for item in report["limitations"])


def test_headless_cli_emits_a_valid_deterministic_json_report():
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "experiments.global_availability_selective_ablation",
        "--seed",
        "headless-cli-test",
    ]
    first = subprocess.run(
        command, cwd=root, capture_output=True, text=True, check=False
    )
    second = subprocess.run(
        command, cwd=root, capture_output=True, text=True, check=False
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stderr == ""
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["status"] == "passed"
    assert report["execution_performed"] is False
    assert report["persistent_writes"] is False


@pytest.mark.parametrize("restored_domain", DOMAINS)
def test_reinstating_ablation_restores_all_subscribers(restored_domain):
    report = run_experiment()
    case = _conditions(report)[f"subscriber_restoration:{restored_domain}"]

    assert case["restored_domain"] == restored_domain
    assert case["observed_domains"] == list(DOMAINS)
    assert case["missing_domains"] == []
    assert case["unexpected_domains"] == []
    assert case["restoration_passed"] is True


@pytest.mark.parametrize("seed", [None, "", " ", "x" * 257, 42])
def test_invalid_experiment_seed_is_rejected(seed):
    with pytest.raises(ValueError):
        run_experiment(seed)


def test_report_sha256_recomputes_from_canonical_payload():
    report = run_experiment("hash-check")
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    import hashlib

    assert report["report_sha256"] == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
