import pytest

from agent.reasoning_engine import ReasoningEngine, ReasoningEngineError


def test_reasoning_engine_derives_with_source_confidence_and_provenance():
    result = ReasoningEngine().reason(
        facts=[{"statement": "solo molhado", "source": "sensor", "confidence": 0.9}],
        rules=[{
            "if_all": ["solo molhado"],
            "then": "risco de escorregamento",
            "source": "regra validada",
            "confidence": 0.8,
        }],
    )
    assert result["status"] == "completed"
    assert result["derived_count"] == 1
    assert result["derived"][0]["source"] == "regra validada"
    assert result["derived"][0]["derived_from"] == ["solo molhado"]
    assert result["derived"][0]["confidence"] == pytest.approx(0.72)


def test_reasoning_engine_reports_explicit_contradiction():
    result = ReasoningEngine().reason(
        facts=["porta aberta", "porta fechada"],
        rules=[],
        contradiction_pairs=[["porta aberta", "porta fechada"]],
    )
    assert result["status"] == "contradiction_detected"
    assert result["consistent"] is False
    assert len(result["contradictions"]) == 1


def test_reasoning_engine_does_not_infer_negation_from_missing_fact():
    result = ReasoningEngine().reason(
        facts=["porta aberta"],
        rules=[{
            "if_all": ["porta fechada"],
            "then": "alarme ativo",
        }],
    )
    assert result["derived_count"] == 0
    assert result["status"] == "completed"


def test_reasoning_engine_rejects_invalid_confidence():
    with pytest.raises(ReasoningEngineError, match="Confiança"):
        ReasoningEngine().reason(
            facts=[{"statement": "fato", "confidence": 1.5}],
            rules=[],
        )


def test_reasoning_engine_does_not_persist_by_default():
    result = ReasoningEngine().demonstrate_capabilities()
    assert result["passed"] is True
    assert result["memory_modified"] is False
    assert result["external_actions"] is False


def test_reasoning_engine_persistence_requires_cognitive_connection():
    with pytest.raises(RuntimeError, match="não foi conectado"):
        ReasoningEngine().reason(facts=["fato"], rules=[], persist=True)


def test_duplicate_facts_preserve_all_reports_without_confidence_inflation():
    result = ReasoningEngine().reason(
        facts=[
            {"statement": "solo molhado", "source": "sensor-a", "confidence": 0.95},
            {"statement": " Solo   molhado ", "source": "sensor-b", "confidence": 0.80},
            {"statement": "solo molhado", "source": "sensor-a", "confidence": 0.99},
        ],
        rules=[{
            "if_all": ["solo molhado"],
            "then": "risco de escorregamento",
            "source": "regra",
            "confidence": 0.5,
        }],
    )

    fact = next(item for item in result["facts"] if item["statement"] == "solo molhado")
    derived = result["derived"][0]

    assert fact["source"] == "sensor-a"
    assert fact["supporting_sources"] == ["sensor-a", "sensor-b"]
    assert len(fact["supporting_reports"]) == 3
    assert fact["confidence"] == pytest.approx(0.80)
    assert fact["confidence_aggregation"] == "minimum_reported_confidence"
    assert fact["source_identity_verified"] is False
    assert derived["confidence"] == pytest.approx(0.40)
    premise = derived["premise_evidence"][0]
    assert premise["statement"] == "solo molhado"
    assert premise["supporting_sources"] == ["sensor-a", "sensor-b"]
    assert premise["confidence"] == pytest.approx(0.80)
    assert premise["epistemic_state"] == "caller_reported_unverified"
    assert set(derived["supporting_sources"]) == {"regra", "sensor-a", "sensor-b"}
    assert derived["source_identity_verified"] is False


def test_reasoning_rejects_unrepresentable_confidence_values():
    with pytest.raises(ReasoningEngineError, match="finita"):
        ReasoningEngine().reason(
            facts=[{"statement": "fato", "confidence": 10 ** 10000}],
            rules=[],
        )
