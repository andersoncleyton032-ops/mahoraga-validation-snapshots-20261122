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
