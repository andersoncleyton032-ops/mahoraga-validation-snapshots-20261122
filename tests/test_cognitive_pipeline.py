import pytest

from agent.dharma import Decision, Dharma
from agent.integration_core import IntegratedCore
from agent.knowledge_engine import KnowledgeEngine
from agent.cognitive_engine import CognitiveEngine
from agent.store import KnowledgeStore


class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


def make_core(tmp_path, dharma=None):
    store = KnowledgeStore(tmp_path / "pipeline.sqlite3")
    core = IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=FakeHardware(),
        dharma=dharma,
    )
    return core, store


def test_language_reasoning_and_research_share_the_cognitive_core(tmp_path):
    core, _ = make_core(tmp_path)

    assert core.language.cognitive is core.cognitive
    assert core.research_orchestrator.cognitive is core.cognitive
    assert core.reasoning is core.cognitive.reasoning
    assert core.knowledge.store is core.cognitive.store
    assert core.tools.store is core.cognitive.store


def test_shared_component_validator_detects_detached_language(tmp_path):
    core, _ = make_core(tmp_path)
    core.language.cognitive = object()

    try:
        core._validate_shared_components()
    except RuntimeError as exc:
        assert "language_cognitive" in str(exc)
    else:
        raise AssertionError("LanguageEngine separado do núcleo foi aceito.")


def test_prepare_request_combines_shared_capabilities_without_side_effects(
    tmp_path,
):
    core, store = make_core(tmp_path)
    source = tmp_path / "context.md"
    source.write_text(
        "A recuperação contextual do Mahoraga mantém a origem e o hash "
        "dos fragmentos para revisão cognitiva.",
        encoding="utf-8",
    )
    imported = core.knowledge.import_document(source, subject="cognition")
    assert imported["status"] == "imported"

    core.language.classify = lambda _text: {
        "recognized": True,
        "decision": "recognize",
        "intent": "status",
        "confidence": 0.95,
        "margin": 0.70,
        "reason": None,
    }
    counts_before = store.counts()
    events_before = store.list_events(limit=500)

    result = core.prepare_request(
        "Como o Mahoraga preserva o contexto cognitivo?",
        knowledge_query="recuperação contextual Mahoraga",
        knowledge_subject="cognition",
        facts=["memória compartilhada"],
        rules=[{
            "if_all": ["memória compartilhada"],
            "then": "contexto integrado",
            "source": "regra de teste",
        }],
        include_capability_review=True,
    )

    assert result["schema"] == "mahoraga.request_preparation"
    assert result["plan"]["status"] == "ready_for_human_review"
    assert result["plan"]["intent"] == "status"
    assert result["knowledge"]["status"] == "retrieved"
    assert result["knowledge"]["matches"][0]["document_id"] == imported["document_id"]
    assert result["knowledge"]["matches"][0]["knowledge_status"] == "prepared_not_learned"
    assert result["reasoning"]["status"] == "completed"
    assert result["reasoning"]["result"]["derived_count"] == 1
    assert result["capability_review"]["status"] == "completed"
    assert result["research"]["execution_performed"] is False
    assert result["side_effects"] == {
        "memory_modified": False,
        "learning_persisted": False,
        "neural_training_performed": False,
        "prototype_learning_performed": False,
        "tools_executed": False,
        "external_actions_performed": False,
    }
    assert store.counts() == counts_before
    assert store.list_events(limit=500) == events_before


def test_prepare_request_keeps_deferred_intentions_non_executable(tmp_path):
    core, store = make_core(tmp_path)
    core.language.classify = lambda _text: {
        "recognized": False,
        "decision": "defer",
        "intent": "blender.inspect",
        "reason": "future_or_conditional_intention",
    }
    before = store.list_events(limit=500)

    result = core.prepare_request(
        "Amanhã analise a cena no Blender.",
        knowledge_query="cena Blender",
        include_capability_review=False,
    )

    assert result["plan"]["status"] == "deferred"
    assert result["plan"]["execution_authorized"] is False
    assert result["plan"]["execution_performed"] is False
    assert result["research"]["execution_performed"] is False
    assert store.list_events(limit=500) == before


def test_prepare_request_requires_clarification_for_ambiguous_language(tmp_path):
    core, _ = make_core(tmp_path)
    core.language.classify = lambda _text: {
        "recognized": False,
        "decision": "clarify",
        "intent": None,
        "reason": "ambiguous_reference",
    }

    result = core.prepare_request(
        "Talvez analise isso.",
        include_capability_review=False,
    )

    assert result["plan"]["status"] == "clarification_required"
    assert result["plan"]["execution_performed"] is False


def test_context_can_be_returned_without_inventing_an_intent(tmp_path):
    core, _ = make_core(tmp_path)
    source = tmp_path / "notes.txt"
    source.write_text(
        "O núcleo cognitivo compartilha a memória e a proveniência documental.",
        encoding="utf-8",
    )
    core.knowledge.import_document(source, subject="cognition")
    core.language.classify = lambda _text: {
        "recognized": False,
        "decision": "abstain",
        "intent": None,
        "reason": "model_not_trained",
    }

    result = core.prepare_request(
        "Explique a memória do núcleo.",
        knowledge_query="memória núcleo cognitivo",
        knowledge_subject="cognition",
        include_capability_review=False,
    )

    assert result["plan"]["status"] == "context_only"
    assert result["plan"]["intent"] is None
    assert result["knowledge"]["result_count"] == 1
    assert result["plan"]["execution_performed"] is False


def test_request_with_no_informative_retrieval_terms_is_degraded_safely(tmp_path):
    core, _ = make_core(tmp_path)
    core.language.classify = lambda _text: {
        "recognized": False,
        "decision": "abstain",
        "intent": None,
        "reason": "model_not_trained",
    }

    result = core.prepare_request(
        "a e de",
        include_capability_review=False,
    )

    assert result["knowledge"]["status"] == "skipped"
    assert result["knowledge"]["reason"] == "query_without_informative_terms"
    assert result["plan"]["status"] == "not_recognized"


def test_explicit_reasoning_conflict_blocks_ready_plan(tmp_path):
    core, _ = make_core(tmp_path)
    core.language.classify = lambda _text: {
        "recognized": True,
        "decision": "recognize",
        "intent": "status",
        "confidence": 0.95,
        "margin": 0.70,
    }

    result = core.prepare_request(
        "Mostre o estado.",
        knowledge_query="estado Mahoraga",
        facts=["porta aberta", "porta fechada"],
        rules=[],
        contradiction_pairs=[["porta aberta", "porta fechada"]],
        include_capability_review=False,
    )

    assert result["reasoning"]["status"] == "contradiction_detected"
    assert result["plan"]["status"] == "requires_review"
    assert result["plan"]["execution_performed"] is False


def test_prepare_request_validates_bounds_and_boolean_flags(tmp_path):
    core, _ = make_core(tmp_path)

    for invalid_limit in (0, 21, True, 1.5):
        try:
            core.prepare_request(
                "Estado do Mahoraga",
                knowledge_limit=invalid_limit,
                include_capability_review=False,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"Limite inválido aceito: {invalid_limit!r}")

    try:
        core.prepare_request(
            "Estado do Mahoraga",
            include_capability_review=1,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Flag não booleana foi aceita.")


def test_cognitive_retrieve_knowledge_is_provenance_preserving_and_read_only(
    tmp_path,
):
    store = KnowledgeStore(tmp_path / "retrieval.sqlite3")
    knowledge = KnowledgeEngine(store)
    cognitive = CognitiveEngine(
        store=store,
        knowledge=knowledge,
        dharma=Dharma(),
    )
    source = tmp_path / "hardware.md"
    source.write_text(
        "A temperatura do processador deve ser monitorada durante carga sustentada.",
        encoding="utf-8",
    )
    imported = knowledge.import_document(source, subject="hardware")
    counts_before = store.counts()
    events_before = store.list_events(limit=100)

    result = cognitive.retrieve_knowledge(
        "temperatura processador",
        subject="hardware",
    )

    assert result["status"] == "retrieved"
    assert result["ranking_method"] == "bm25_lexical_v1"
    assert result["knowledge_status"] == "prepared_not_learned"
    assert result["matches"][0]["document_id"] == imported["document_id"]
    assert result["matches"][0]["chunk_sha256"]
    assert result["neural_training_performed"] is False
    assert result["memory_modified"] is False
    assert store.counts() == counts_before
    assert store.list_events(limit=100) == events_before


def test_cognitive_retrieve_knowledge_obeys_dharma_read_policy(tmp_path):
    class DenyRead(Dharma):
        def evaluate(self, action, target="", context=None):
            if action == "read_project":
                return Decision(
                    allowed=False,
                    requires_approval=True,
                    reason="Leitura bloqueada pelo teste.",
                    risk_score=70,
                    category="test",
                    reversible=True,
                )
            return super().evaluate(action, target, context)

    store = KnowledgeStore(tmp_path / "denied-retrieval.sqlite3")
    cognitive = CognitiveEngine(
        store=store,
        knowledge=KnowledgeEngine(store),
        dharma=DenyRead(tmp_path),
    )

    try:
        cognitive.retrieve_knowledge("temperatura processador")
    except PermissionError as exc:
        assert "Leitura bloqueada" in str(exc)
    else:
        raise AssertionError("A recuperação ignorou a política Dharma.")

    assert store.counts()["documents"] == 0


def test_integrated_core_reviews_initiatives_from_shared_self_model_read_only(
    tmp_path,
):
    core, store = make_core(tmp_path)
    counts_before = store.counts()
    events_before = store.list_events(limit=500)

    review = core.cognitive.review_initiatives()

    assert review["status"] == "reviewed"
    assert review["sources"]["operational_self_model"] == "reviewed"
    assert review["candidate_count"] >= 6
    assert any(
        item["kind"] == "self_inquiry"
        and item["evidence"]["epistemic_state"] == "open_question_not_conclusion"
        for item in review["candidates"]
    )
    assert review["execution_performed"] is False
    assert review["memory_modified"] is False
    assert store.counts() == counts_before
    assert store.list_events(limit=500) == events_before



def test_integrated_core_prepares_initiative_research_without_execution(tmp_path):
    core, store = make_core(tmp_path)
    candidate = {
        "candidate_id": "capability:" + "b" * 24,
        "kind": "capability_gap",
        "title": "Avaliar capacidade: ferramenta de diagnóstico",
        "description": "Como medir a latência do diagnóstico local?",
        "source": "capability_audit",
        "evidence": {"status": "candidate_not_tested"},
    }
    core.cognitive.review_initiatives = lambda: {
        "status": "reviewed",
        "candidates": [candidate],
    }
    before = store.counts()

    try:
        core.prepare_initiative_research(candidate["candidate_id"])
    except PermissionError:
        pass
    else:
        raise AssertionError("Plano foi persistido sem aprovação explícita.")
    assert store.counts() == before

    result = core.prepare_initiative_research(
        candidate["candidate_id"], approved=True
    )
    assert result["status"] == "prepared"
    assert result["plan"]["candidate_id"] == candidate["candidate_id"]
    assert result["plan"]["status"] == "prepared_pending_execution_review"
    assert result["plan"]["governance"]["human_review_required_before_execution"] is True
    assert result["execution_performed"] is False
    assert result["tool_dispatch_performed"] is False
    assert core.research_orchestrator.store is core.store
    assert core.research_orchestrator.cognitive is core.cognitive
    assert len(store.load_memories()) == 1



def test_integrated_research_plan_result_reaches_shared_adaptive_memory(tmp_path):
    core, store = make_core(tmp_path)
    candidate = {
        "candidate_id": "experience:" + "a" * 24,
        "kind": "experience_pattern",
        "title": "Investigar padrão recorrente: testes de integração",
        "description": "A recuperação de checkpoints mantém a integridade após falhas?",
        "priority": "normal",
        "source": "adaptive_learning",
        "evidence": {"event_ids": [10, 11, 12]},
    }
    core.cognitive.review_initiatives = lambda: {
        "status": "reviewed",
        "candidates": [candidate],
    }
    plan = core.prepare_initiative_research(
        candidate["candidate_id"], approved=True
    )["plan"]
    report = {
        "plan_id": plan["plan_id"],
        "method": "Executar a matriz de recuperação com checkpoints corrompidos.",
        "result_status": "completed",
        "summary": "Os casos de fallback passaram no ambiente de CI.",
        "evidence_refs": [
            "https://github.com/andersoncleyton032-ops/mahoraga-core/actions/runs/589",
            "commit:" + "b" * 40,
        ],
    }

    before_events = store.list_events(
        limit=100, event_type="adaptive.experience.recorded"
    )
    try:
        core.record_research_result(**report)
    except PermissionError:
        pass
    else:
        raise AssertionError("Resultado foi registrado sem aprovação.")
    assert store.list_events(
        limit=100, event_type="adaptive.experience.recorded"
    ) == before_events

    recorded = core.record_research_result(**report, approved=True)
    assert recorded["status"] == "research_result_recorded"
    assert recorded["event_created"] is True
    assert recorded["plan_id"] == plan["plan_id"]
    assert recorded["report_provenance"] == "caller_supplied_not_independently_verified"
    assert recorded["plan_state_changed"] is False
    assert recorded["research_executed_by_this_call"] is False
    assert recorded["semantic_consolidation_performed"] is False
    assert recorded["learning_state"] == "episodic_only"

    repeated = core.record_research_result(**report, approved=True)
    assert repeated["event_created"] is False
    assert repeated["event_id"] == recorded["event_id"]

    second_report = dict(
        report,
        attempt_id="rerun-2",
        method="Repetir a matriz completa em uma segunda execução.",
        summary="A segunda execução confirmou o mesmo resultado.",
        evidence_refs=["ci://run/590"],
    )
    second_attempt = core.record_research_result(
        **second_report, approved=True
    )
    assert second_attempt["event_created"] is True

    third_report = dict(
        report,
        attempt_id="review-3",
        method="Revisar a mesma matriz após mudança no ambiente.",
        result_status="inconclusive",
        summary="A mudança no ambiente impediu uma conclusão comparável.",
        evidence_refs=["ci://run/591"],
    )
    third_attempt = core.record_research_result(
        **third_report, approved=True
    )
    assert third_attempt["event_created"] is True

    history = core.list_research_results(plan["plan_id"])
    assert history["result_count"] == 3
    assert history["result_limit_reached"] is False
    assert history["review_scope_complete"] is True
    assert {item["attempt_id"] for item in history["results"]} == {
        "initial", "rerun-2", "review-3"
    }
    assert history["consistency_status"] == "mixed_attempt_outcomes"
    assert history["review_required"] is True
    assert history["result_status_counts"] == {
        "completed": 2, "inconclusive": 1
    }
    assert history["memory_modified"] is False
    assert history["execution_performed"] is False

    bounded_history = core.list_research_results(
        plan["plan_id"], limit=1
    )
    assert bounded_history["result_count"] == 1
    assert bounded_history["result_limit_reached"] is True
    assert bounded_history["review_scope_complete"] is False
    assert bounded_history["review_required"] is True

    orchestrator_status = core.research_orchestrator.status()
    assert orchestrator_status["research_result_feedback_enabled"] is True
    assert orchestrator_status["automatic_result_verification"] is False
    assert orchestrator_status["automatic_semantic_consolidation"] is False

    episode_events = store.list_events(
        limit=100, event_type="adaptive.experience.recorded"
    )
    assert len(episode_events) == 3
    episode = episode_events[0]["payload"]
    assert episode["validated"] is False
    assert episode["references"]["research_plan_id"] == plan["plan_id"]
    assert episode["references"]["initiative_candidate_id"] == candidate["candidate_id"]
    assert episode["references"]["reported_by"] == "caller_supplied_not_independently_verified"

    replay = core.cognitive.review_experiences()
    assert replay["replayed_episode_count"] == 3
    assert replay["candidate_count"] == 0
    assert store.get_memory("research_plan:" + plan["plan_id"])["value"]["status"] == "prepared_pending_execution_review"


def test_integrated_research_result_rejects_missing_plan(tmp_path):
    core, store = make_core(tmp_path)
    with pytest.raises(ValueError, match="Plano inexistente"):
        core.record_research_result(
            "research-" + "c" * 24,
            method="Teste local",
            result_status="failed",
            summary="Plano ausente.",
            evidence_refs=["artifact://failure"],
            approved=True,
        )
    assert store.list_events(
        limit=100, event_type="adaptive.experience.recorded"
    ) == []



def test_integrated_cognitive_review_surfaces_research_conflict(tmp_path):
    core, store = make_core(tmp_path)
    core.cognitive.review_capabilities = lambda persist=False: {
        "status": "reviewed",
        "assessment": {"candidate_hypotheses": []},
    }
    plan_id = "research-" + "d" * 24

    for attempt_id, result_status in (
        ("initial", "completed"),
        ("verification-2", "failed"),
    ):
        store.record_event(
            "adaptive.experience.recorded",
            {
                "task": "research initiative capability_gap",
                "outcome": result_status,
                "validated": False,
                "learning_state": "episodic_only",
                "references": {
                    "research_plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "result_status": result_status,
                    "reported_by": "caller_supplied_not_independently_verified",
                },
            },
        )

    counts_before = store.counts()
    review = core.cognitive.review_initiatives()

    assert store.counts() == counts_before
    assert review["memory_modified"] is False
    candidate = next(
        item for item in review["candidates"]
        if item["kind"] == "research_result_conflict"
    )
    assert candidate["evidence"]["research_plan_id"] == plan_id
    assert candidate["evidence"]["result_statuses"] == [
        "completed", "failed"
    ]
    assert review["sources"]["research_result_history"] == "reviewed"
    assert review["execution_performed"] is False
