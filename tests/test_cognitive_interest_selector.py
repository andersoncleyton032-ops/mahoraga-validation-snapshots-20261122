import pytest

from experiments.cognitive_interest_selector import (
    CognitiveInterestSelector,
    InterestBudget,
    InterestSelectionError,
)


def candidate(candidate_id, **overrides):
    value = {
        "candidate_id": candidate_id,
        "topic": f"investigar {candidate_id}",
        "relevance": 0.8,
        "novelty": 0.5,
        "uncertainty": 0.7,
        "controllability": 0.9,
        "learning_progress": 0.6,
        "expected_transfer": 0.8,
        "noise_risk": 0.1,
        "estimated_runtime_ms": 100,
        "estimated_ram_mb": 16,
        "dependencies": [],
        "evidence_refs": [],
    }
    value.update(overrides)
    return value


def test_selector_prefers_learnable_and_transferable_question():
    selector = CognitiveInterestSelector()
    useful = candidate(
        "useful", relevance=0.9, controllability=0.95,
        learning_progress=0.9, expected_transfer=0.9, noise_risk=0.0,
    )
    noisy = candidate(
        "noisy", relevance=0.1, novelty=1.0, uncertainty=1.0,
        controllability=0.0, learning_progress=0.0,
        expected_transfer=0.0, noise_risk=1.0,
    )
    result = selector.select([noisy, useful], InterestBudget(1000, 128))
    assert result["selected_roots"][0] == "useful"
    assert result["execution_performed"] is False
    assert result["authorization_granted"] is False


def test_novelty_alone_does_not_dominate_learning_value():
    selector = CognitiveInterestSelector()
    novelty_only = candidate(
        "novel", relevance=0.0, novelty=1.0, uncertainty=1.0,
        controllability=0.0, learning_progress=0.0,
        expected_transfer=0.0, noise_risk=0.0,
    )
    learning = candidate(
        "learning", relevance=0.7, novelty=0.1, uncertainty=0.8,
        controllability=0.9, learning_progress=0.9,
        expected_transfer=0.9, noise_risk=0.0,
    )
    result = selector.select([novelty_only, learning], InterestBudget(1000, 128))
    assert result["selected_roots"][0] == "learning"


def test_uncertainty_only_matters_when_it_is_controllable():
    selector = CognitiveInterestSelector()
    uncontrollable = candidate(
        "uncontrollable", uncertainty=1.0, controllability=0.0,
        relevance=0.1, novelty=0.0, learning_progress=0.0,
        expected_transfer=0.0, noise_risk=0.0,
    )
    controllable = candidate(
        "controllable", uncertainty=0.8, controllability=1.0,
        relevance=0.1, novelty=0.0, learning_progress=0.0,
        expected_transfer=0.0, noise_risk=0.0,
    )
    result = selector.select([uncontrollable, controllable], InterestBudget(1000, 128))
    assert result["selected_roots"][0] == "controllable"


def test_dependencies_are_included_once_in_aggregate_budget():
    selector = CognitiveInterestSelector()
    items = [
        candidate("shared", estimated_runtime_ms=100, estimated_ram_mb=20),
        candidate("a", dependencies=["shared"], estimated_runtime_ms=200, estimated_ram_mb=30),
        candidate("b", dependencies=["shared"], estimated_runtime_ms=300, estimated_ram_mb=40),
    ]
    result = selector.select(items, InterestBudget(600, 90, max_selected=3))
    assert set(result["selected_order"]) == {"shared", "a", "b"}
    assert result["aggregate_cost"] == {
        "runtime_ms": 600, "ram_mb": 90, "selected_count": 3,
    }


def test_dependency_closure_is_rejected_atomically_when_budget_exceeded():
    selector = CognitiveInterestSelector()
    items = [
        candidate(
            "prerequisite", relevance=0.0, novelty=0.0, uncertainty=0.0,
            controllability=0.0, learning_progress=0.0,
            expected_transfer=0.0, noise_risk=1.0,
            estimated_runtime_ms=400,
        ),
        candidate("root", dependencies=["prerequisite"], estimated_runtime_ms=400),
    ]
    result = selector.select(items, InterestBudget(500, 128))
    assert "root" not in result["selected_roots"]
    rejected = {item["candidate_id"]: item["reason"] for item in result["rejected"]}
    assert rejected["root"] == "aggregate_runtime_budget"


def test_missing_dependency_and_cycle_are_rejected():
    selector = CognitiveInterestSelector()
    with pytest.raises(InterestSelectionError, match="Dependência ausente"):
        selector.select(
            [candidate("root", dependencies=["missing"])],
            InterestBudget(1000, 128),
        )
    with pytest.raises(InterestSelectionError, match="Ciclo"):
        selector.select(
            [candidate("a", dependencies=["b"]), candidate("b", dependencies=["a"])],
            InterestBudget(1000, 128),
        )


def test_selection_is_deterministic_under_input_order_permutation():
    selector = CognitiveInterestSelector()
    items = [candidate("c"), candidate("a"), candidate("b")]
    left = selector.select(items, InterestBudget(1000, 128))
    right = selector.select(list(reversed(items)), InterestBudget(1000, 128))
    assert left == right


def test_empty_or_low_value_candidates_abstain():
    selector = CognitiveInterestSelector()
    result = selector.select(
        [candidate(
            "weak", relevance=0.0, novelty=0.0, uncertainty=0.0,
            controllability=0.0, learning_progress=0.0,
            expected_transfer=0.0, noise_risk=1.0,
        )],
        InterestBudget(1000, 128),
    )
    assert result["status"] == "abstain"
    assert result["selected_order"] == []


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -0.1, 1.1, "0.5"])
def test_candidate_scores_reject_invalid_numeric_values(bad):
    with pytest.raises(InterestSelectionError):
        CognitiveInterestSelector().select(
            [candidate("bad", novelty=bad)],
            InterestBudget(1000, 128),
        )


def test_budget_rejects_boolean_and_nonpositive_limits():
    with pytest.raises(InterestSelectionError):
        InterestBudget(True, 128)
    with pytest.raises(InterestSelectionError):
        InterestBudget(1000, 0)


def test_duplicate_ids_and_oversized_candidate_sets_are_rejected():
    selector = CognitiveInterestSelector()
    with pytest.raises(InterestSelectionError, match="duplicado"):
        selector.select(
            [candidate("same"), candidate("same")],
            InterestBudget(1000, 128),
        )
    with pytest.raises(InterestSelectionError, match="Lista de candidatos"):
        selector.select(
            [candidate(str(index)) for index in range(selector.MAX_CANDIDATES + 1)],
            InterestBudget(1000, 128),
        )


def test_evidence_refs_are_reported_as_unverified():
    result = CognitiveInterestSelector().select(
        [candidate("with-evidence", evidence_refs=["paper:example"])],
        InterestBudget(1000, 128),
    )
    row = result["ranking"][0]
    assert row["evidence_state"] == "caller_declared_unverified"
    assert row["evidence_refs"] == ["paper:example"]


def test_plan_hash_is_stable_and_covers_plan_content():
    selector = CognitiveInterestSelector()
    items = [candidate("one"), candidate("two", novelty=0.9)]
    first = selector.select(items, InterestBudget(1000, 128))
    second = selector.select(items, InterestBudget(1000, 128))
    assert first["plan_sha256"] == second["plan_sha256"]
    assert len(first["plan_sha256"]) == 64
