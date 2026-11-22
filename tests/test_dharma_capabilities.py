from agent.dharma import Dharma


def test_unknown_action_allows_investigation_but_not_execution():
    decision = Dharma().evaluate("unknown_capability")

    assert decision.allowed is False
    assert decision.requires_approval is False
    assert decision.discovery_allowed is True
    assert decision.experiment_allowed is False
    assert decision.promotion_allowed is False


def test_internal_persistence_has_explicit_classification():
    dharma = Dharma()

    for action in (
        "record_learning",
        "record_observation",
        "record_experiment",
    ):
        decision = dharma.evaluate(action)

        assert decision.allowed is True
        assert decision.category == "internal_persistence"


def test_valid_sandbox_operation_allows_experimentation():
    decision = Dharma().evaluate(
        "run_sandbox_test",
        "sandbox/workspace/test.py",
    )

    assert decision.allowed is True
    assert decision.experiment_allowed is True
    assert decision.promotion_allowed is False


def test_project_modification_requires_approval():
    decision = Dharma().evaluate(
        "modify_project",
        context={"writes_project": True},
    )

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.promotion_allowed is False


def test_protected_actions_remain_blocked():
    decision = Dharma().evaluate("modify_policy")

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.discovery_allowed is False
    assert decision.experiment_allowed is False
    assert decision.promotion_allowed is False



def test_read_only_capability_is_authorized_for_discovery_only():
    decision = Dharma().evaluate("read_only_capability")

    assert decision.allowed is True
    assert decision.risk_score == 5
    assert decision.discovery_allowed is True
    assert decision.experiment_allowed is False
    assert decision.promotion_allowed is False


def test_local_compute_is_authorized_for_controlled_experiments():
    decision = Dharma().evaluate("local_compute")

    assert decision.allowed is True
    assert decision.risk_score == 20
    assert decision.discovery_allowed is True
    assert decision.experiment_allowed is True
    assert decision.promotion_allowed is False


def test_capability_with_external_effect_requires_approval():
    decision = Dharma().evaluate(
        "local_compute",
        context={"external_side_effect": True},
    )

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.experiment_allowed is False
    assert decision.promotion_allowed is False


def test_capability_with_project_write_requires_approval():
    decision = Dharma().evaluate(
        "read_only_capability",
        context={"writes_project": True},
    )

    assert decision.allowed is False
    assert decision.requires_approval is True
