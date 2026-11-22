import pytest

from agent.cognitive_engine import CognitiveEngine
from agent.dharma import Decision, Dharma
from agent.knowledge_engine import KnowledgeEngine
from agent.store import KnowledgeStore


@pytest.fixture
def engine(tmp_path):
    store = KnowledgeStore(str(tmp_path / "cognitive-test.sqlite3"))
    knowledge = KnowledgeEngine(store)
    return CognitiveEngine(store=store, knowledge=knowledge, dharma=Dharma())


def test_status_reports_components(engine):
    result = engine.status()
    assert result["component"] == "CognitiveEngine"
    assert result["knowledge"]["documents"] == 0
    assert result["storage"]["memories"] == 0
    assert result["neural_training"] == "not_automatically_connected"


def test_record_observation(engine):
    result = engine.record_observation(
        category="performance",
        subject="cpu",
        data={"temperature_c": 38.5},
        source="device_sensor",
        confidence=0.9,
        limitations=["single measurement"],
    )
    assert result["status"] == "recorded"
    assert engine.store.counts()["observations"] == 1
    event = engine.store.list_events(
        event_type="cognitive.observation.recorded"
    )[0]
    assert event["payload"]["subject"] == "cpu"


def test_record_learning(engine):
    result = engine.record_learning(
        key="thermal_behavior",
        learning={"finding": "temperature increased under sustained load"},
        source="controlled_test",
    )
    assert result["status"] == "recorded"
    saved = engine.store.load_memories()["thermal_behavior"]
    assert saved["value"]["finding"] == "temperature increased under sustained load"
    assert saved["metadata"]["source"] == "controlled_test"


def test_propose_hypothesis(engine):
    result = engine.propose_hypothesis(
        hypothesis="Reducing bloom may improve frame stability",
        question="Does disabling bloom reduce frame-time spikes?",
    )
    assert result["status"] == "proposed_not_tested"
    event = engine.store.list_events(
        event_type="cognitive.hypothesis.proposed"
    )[0]
    assert event["payload"]["cycle_id"] == result["cycle_id"]
    assert event["payload"]["status"] == "proposed_not_tested"


def test_complete_experiment(engine):
    result = engine.complete_experiment(
        hypothesis="A controlled change reduces frame-time spikes",
        method="Compare two runs with the same scene and duration",
        result="The second run had fewer spikes",
        conclusion="Preliminary support; repeat the test",
        cycle_id="cycle-001",
    )
    assert result["status"] == "recorded"
    saved = engine.store.list_experiments(limit=1)[0]
    assert saved["metadata"]["cognitive_cycle_id"] == "cycle-001"
    assert saved["conclusion"] == "Preliminary support; repeat the test"


def test_prepare_document_learning(engine, tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text(
        "Thermal behavior should be measured under repeatable load.",
        encoding="utf-8",
    )
    imported = engine.knowledge.import_document(
        str(source), subject="hardware"
    )
    document = engine.knowledge.list_documents(
        subject="hardware", limit=10
    )[0]
    prepared = engine.prepare_document_learning(document["id"])

    assert imported["status"] == "imported"
    assert prepared["status"] == "prepared_not_learned"
    assert prepared["neural_training_performed"] is False
    assert prepared["chunks"]


def test_unknown_document_is_rejected(engine):
    with pytest.raises(ValueError, match="Documento não encontrado"):
        engine.prepare_document_learning(999999)


def test_invalid_hypothesis_and_experiment_are_rejected(engine):
    with pytest.raises(ValueError, match="hipótese"):
        engine.propose_hypothesis("  ", "A valid question")

    with pytest.raises(ValueError, match="result não pode estar vazio"):
        engine.complete_experiment("H", "M", "  ", "C")


def test_review_context_validates_limits(engine):
    with pytest.raises(ValueError, match="event_limit"):
        engine.review_context(event_limit=0)


def test_dharma_denial_prevents_observation_write(tmp_path):
    class DenyObservations(Dharma):
        def evaluate(self, action, target="", context=None):
            return Decision(
                allowed=False,
                requires_approval=True,
                reason="Blocked by test policy",
                risk_score=80,
                category="test",
                reversible=True,
            )

    store = KnowledgeStore(str(tmp_path / "denied-test.sqlite3"))
    engine = CognitiveEngine(store=store, dharma=DenyObservations())

    with pytest.raises(PermissionError, match="Blocked by test policy"):
        engine.record_observation("test", "subject", {}, "test")

    assert store.counts()["observations"] == 0



def test_review_capabilities_requires_introspection(engine):
    with pytest.raises(RuntimeError, match="IntrospectionEngine não conectado"):
        engine.review_capabilities()


def test_review_capabilities_is_read_only_and_marks_candidates(engine):
    class FakeIntrospection:
        def audit_capabilities(self, limit_experiments=50, persist=True):
            return {
                "status": "completed",
                "tool_count": 1,
                "evidence_sufficient_count": 0,
                "evidence_insufficient_count": 1,
                "tools": [{"tool_id": "python"}],
                "recommendations": [{
                    "tool_id": "python",
                    "priority": "high",
                    "reason": "Evidência insuficiente.",
                    "action": "Executar e registrar evidências adicionais.",
                }],
                "limitations": ["Auditoria baseada em registros."],
                "persistence": None,
            }

    engine.introspection = FakeIntrospection()
    before = engine.store.counts()
    events_before = engine.store.list_events(limit=500)

    result = engine.review_capabilities(persist=False)

    assert result["status"] == "reviewed"
    assert result["execution_performed"] is False
    assert result["hypotheses_registered"] is False
    assert result["assessment"]["recommendation_count"] == 1

    candidate = result["assessment"]["candidate_hypotheses"][0]
    assert candidate["tool_id"] == "python"
    assert candidate["status"] == "candidate_not_tested"
    assert candidate["registered"] is False

    assert engine.store.counts() == before
    assert engine.store.list_events(limit=500) == events_before


def test_review_capabilities_validates_limit(engine):
    class FakeIntrospection:
        def audit_capabilities(self, **kwargs):
            raise AssertionError("A auditoria não deveria ser chamada.")

    engine.introspection = FakeIntrospection()

    with pytest.raises(ValueError, match="limit_experiments"):
        engine.review_capabilities(limit_experiments=0)



def test_review_context_retrieves_relevant_knowledge_with_provenance(
    engine, tmp_path
):
    source = tmp_path / "thermal-notes.md"
    source.write_text(
        "A temperatura do processador aumenta sob carga sustentada. "
        "A CPU deve ser monitorada durante os testes.",
        encoding="utf-8",
    )
    imported = engine.knowledge.import_document(
        source, subject="hardware"
    )

    result = engine.review_context(
        topic="hardware",
        knowledge_query="temperatura processador CPU",
    )

    assert result["knowledge_query"] == "temperatura processador CPU"
    assert result["knowledge_matches"]
    match = result["knowledge_matches"][0]
    assert match["document_id"] == imported["document_id"]
    assert match["file_name"] == "thermal-notes.md"
    assert match["knowledge_status"] == "prepared_not_learned"
    assert match["ranking_method"] == "bm25_lexical_v1"


def test_review_context_rejects_empty_knowledge_query(engine):
    for query in ("", "   ", 123):
        with pytest.raises(ValueError, match="knowledge_query"):
            engine.review_context(knowledge_query=query)


def test_review_context_without_knowledge_query_remains_compatible(engine):
    result = engine.review_context(topic=None)

    assert result["knowledge_query"] is None
    assert result["knowledge_matches"] == []


def test_reasoning_engine_is_shared_with_cognitive_core(engine):
    assert engine.reasoning.cognitive is engine
    assert engine.status()["reasoning"]["component"] == "ReasoningEngine"


def test_cognitive_reasoning_derives_facts_with_provenance(engine):
    result = engine.reason(
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
    assert result["derived"][0]["derived_from"] == ["solo molhado"]
    assert result["derived"][0]["confidence"] == pytest.approx(0.72)
    assert engine.store.counts()["observations"] == 0


def test_cognitive_reasoning_persistence_uses_shared_store(engine):
    result = engine.reason(
        facts=["porta aberta", "porta fechada"],
        rules=[],
        contradiction_pairs=[["porta aberta", "porta fechada"]],
        persist=True,
    )
    assert result["status"] == "contradiction_detected"
    assert engine.store.counts()["observations"] == 1
    assert engine.store.integrity_check() == "ok"


def test_cognitive_reasoning_is_blocked_by_dharma(tmp_path):
    class DenyLocalCompute(Dharma):
        def evaluate(self, action, target="", context=None):
            if action == "local_compute":
                return Decision(
                    allowed=False, requires_approval=True,
                    reason="Local compute blocked", risk_score=80,
                    category="test", reversible=True,
                )
            return super().evaluate(action, target, context)

    store = KnowledgeStore(str(tmp_path / "reasoning-denied.sqlite3"))
    engine = CognitiveEngine(store=store, dharma=DenyLocalCompute())
    with pytest.raises(PermissionError, match="Local compute blocked"):
        engine.reason(facts=["a"], rules=[])
    assert store.counts()["observations"] == 0


def test_cognitive_reasoning_rejects_non_boolean_persist(engine):
    with pytest.raises(ValueError, match="persist deve ser booleano"):
        engine.reason(facts=[], rules=[], persist="yes")


def test_cognitive_math_tools_are_shared_and_read_only(engine):
    before_counts = engine.store.counts()
    before_events = engine.store.list_events(limit=100)

    evaluated = engine.evaluate_math("1/3 + 1/6")
    solved = engine.solve_linear_equation("2*x + 3 = 11")

    assert evaluated["value"]["exact"] == "1/2"
    assert solved["status"] == "solved"
    assert solved["solution"]["exact"] == "4"
    assert solved["verified"] is True
    assert engine.status()["mathematics"]["component"] == "MathematicsEngine"
    assert engine.store.counts() == before_counts
    assert engine.store.list_events(limit=100) == before_events


def test_cognitive_math_tools_obey_dharma_local_compute_policy(tmp_path):
    class DenyLocalCompute(Dharma):
        def evaluate(self, action, target="", context=None):
            if action == "local_compute":
                return Decision(
                    allowed=False,
                    requires_approval=True,
                    reason="Mathematics blocked",
                    risk_score=80,
                    category="test",
                    reversible=True,
                )
            return super().evaluate(action, target, context)

    store = KnowledgeStore(str(tmp_path / "math-denied.sqlite3"))
    engine = CognitiveEngine(store=store, dharma=DenyLocalCompute())
    with pytest.raises(PermissionError, match="Mathematics blocked"):
        engine.solve_linear_equation("x + 1 = 2")
    with pytest.raises(PermissionError, match="Mathematics blocked"):
        engine.evaluate_math("2 + 2")
    assert store.counts()["observations"] == 0


def test_cognitive_linear_system_solver_is_exact_and_dharma_governed(engine):
    result = engine.solve_linear_system([
        "x + y = 5",
        "2*x - y = 1",
    ])
    assert result["status"] == "solved"
    assert result["solution"]["x"]["exact"] == "2"
    assert result["solution"]["y"]["exact"] == "3"
    assert result["verified"] is True

