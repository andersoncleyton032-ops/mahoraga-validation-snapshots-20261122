import pytest
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context

from agent.conversation_engine import ConversationMemoryEngine
from agent.dharma import Dharma
from agent.store import KnowledgeStore


class FakeCognitive:
    def __init__(self, store):
        self.store = store
        self.dharma = Dharma()


def make_engine(tmp_path):
    store = KnowledgeStore(tmp_path / "conversation.sqlite3")
    return ConversationMemoryEngine(FakeCognitive(store)), store


def _record_exchanges_in_process(db_path, session_id, worker_id, count):
    store = KnowledgeStore(db_path)
    engine = ConversationMemoryEngine(FakeCognitive(store))
    return [
        engine.record_exchange(
            session_id,
            f"process-{worker_id}-exchange-{index}",
            topic="process-concurrency",
            approved=True,
        )["exchange_index"]
        for index in range(count)
    ]


def test_session_and_approved_summary_are_persisted_without_raw_turns(tmp_path):
    engine, store = make_engine(tmp_path)
    session = engine.start_session(title="Mahoraga", topic="memória")
    result = engine.record_exchange(
        session["session_id"],
        "O usuário decidiu priorizar memória contextual.",
        topic="memória contextual",
        intent="planejamento",
        entities=["Mahoraga", "KnowledgeStore"],
        open_loops=["avaliar recuperação semântica"],
        decisions=["preservar BM25 como baseline"],
        references=["PR#12"],
        approved=True,
    )
    state = engine.snapshot(session["session_id"])
    assert result["exchange_index"] == 1
    assert state["is_open"] is True
    assert state["topic"] == "memória contextual"
    assert state["open_loops"] == ["avaliar recuperação semântica"]
    assert state["raw_turns_retained"] is False
    event = store.list_events(event_type=engine.EXCHANGE_RECORDED)[0]
    assert event["payload"]["raw_user_message_retained"] is False
    assert event["payload"]["raw_assistant_response_retained"] is False


def test_summary_retention_requires_explicit_approval(tmp_path):
    engine, store = make_engine(tmp_path)
    session = engine.start_session()
    with pytest.raises(PermissionError):
        engine.record_exchange(session["session_id"], "resumo", approved=False)
    assert store.list_events(event_type=engine.EXCHANGE_RECORDED) == []


def test_closed_sessions_cannot_receive_more_exchanges(tmp_path):
    engine, _ = make_engine(tmp_path)
    session = engine.start_session()
    engine.close_session(session["session_id"])
    with pytest.raises(ValueError):
        engine.record_exchange(session["session_id"], "resumo", approved=True)
    assert engine.snapshot(session["session_id"])["status"] == "closed"


def test_context_retrieval_is_read_only_and_bounded(tmp_path):
    engine, store = make_engine(tmp_path)
    session = engine.start_session(topic="identidade")
    engine.record_exchange(
        session["session_id"], "Definimos o perfil operacional.",
        open_loops=["conectar modelo local"], approved=True,
    )
    before = store.counts()
    result = engine.build_context(max_chars=256)
    after = store.counts()
    assert result["status"] == "ready"
    assert result["context_chars"] <= 256
    assert result["raw_turns_retained"] is False
    assert "\n" in result["context"]
    assert "não confiável" in result["context"]
    assert before == after


def test_latest_open_session_is_selected(tmp_path):
    engine, _ = make_engine(tmp_path)
    first = engine.start_session(title="primeira")
    second = engine.start_session(title="segunda")
    assert engine.snapshot()["session_id"] == second["session_id"]
    assert engine.snapshot(first["session_id"])["is_open"] is True


def test_invalid_session_and_oversized_fields_are_rejected(tmp_path):
    engine, store = make_engine(tmp_path)
    session = engine.start_session()
    with pytest.raises(ValueError):
        engine.record_exchange(session["session_id"], "x" * 2100, approved=True)
    with pytest.raises(ValueError):
        engine.record_exchange(session["session_id"], "resumo", entities=["x" * 301], approved=True)
    with pytest.raises(ValueError):
        engine.close_session("missing")
    assert store.list_events(event_type=engine.EXCHANGE_RECORDED) == []



from agent.integration_core import IntegratedCore


class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


def test_conversation_memory_is_shared_with_pipeline_and_introspection(tmp_path):
    store = KnowledgeStore(tmp_path / "integrated-conversation.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())
    assert core.conversation is core.cognitive.conversation
    assert core.conversation.store is core.store
    assert core.introspection.conversation is core.conversation

    session = core.conversation.start_session(topic="identidade")
    core.conversation.record_exchange(
        session["session_id"],
        "O perfil de identidade e o controle executivo foram integrados.",
        open_loops=["conectar adaptador de conversação local"],
        approved=True,
    )
    before = store.counts()
    prepared = core.prepare_request(
        "qual é a próxima etapa da conversa?",
        include_capability_review=False,
    )
    assert prepared["conversation_memory"]["session_id"] == session["session_id"]
    assert prepared["conversation_context"]["status"] == "ready"
    assert "adaptador de conversação local" in prepared["conversation_context"]["context"]
    self_model = core.introspection.build_self_model(persist=False)
    assert self_model["conversation_state"]["session_id"] == session["session_id"]
    assert store.counts() == before


def test_shared_conversation_memory_serializes_concurrent_exchange_indices(tmp_path):
    engine, store = make_engine(tmp_path)
    session = engine.start_session(topic="cognição")
    session_id = session["session_id"]
    exchange_count = 48

    def record(index):
        return engine.record_exchange(
            session_id,
            f"Resumo concorrente {index}",
            topic="cognição",
            entities=[f"entidade-{index}"],
            approved=True,
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(record, range(exchange_count)))

    indices = sorted(item["exchange_index"] for item in results)
    state = engine.snapshot(session_id)
    events = store.list_events(
        limit=100, event_type=engine.EXCHANGE_RECORDED
    )
    stored_indices = sorted(
        event["payload"]["exchange_index"] for event in events
    )

    assert indices == list(range(1, exchange_count + 1))
    assert stored_indices == list(range(1, exchange_count + 1))
    assert state["exchange_count"] == exchange_count
    assert state["status"] == "active"
    assert state["latest_summary"].startswith("Resumo concorrente ")


def test_conversation_exchange_indexes_are_unique_across_processes(tmp_path):
    db_path = tmp_path / "multiprocess-conversation.sqlite3"
    engine = ConversationMemoryEngine(
        FakeCognitive(KnowledgeStore(db_path))
    )
    session = engine.start_session(topic="process-concurrency")
    session_id = session["session_id"]
    process_count = 3
    exchanges_per_process = 8

    with ProcessPoolExecutor(
        max_workers=process_count,
        mp_context=get_context("spawn"),
    ) as executor:
        futures = [
            executor.submit(
                _record_exchanges_in_process,
                str(db_path),
                session_id,
                worker_id,
                exchanges_per_process,
            )
            for worker_id in range(process_count)
        ]
        returned_indices = [
            index
            for future in futures
            for index in future.result(timeout=30)
        ]

    total = process_count * exchanges_per_process
    events = engine.store.list_events(
        limit=100, event_type=engine.EXCHANGE_RECORDED
    )
    stored_indices = sorted(
        event["payload"]["exchange_index"] for event in events
    )

    assert sorted(returned_indices) == list(range(1, total + 1))
    assert stored_indices == list(range(1, total + 1))
    assert engine.snapshot(session_id)["exchange_count"] == total
