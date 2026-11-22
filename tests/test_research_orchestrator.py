import time
from types import SimpleNamespace

import pytest

from agent.dharma import Dharma
from agent.research_orchestrator import ResearchOrchestrator
from agent.store import KnowledgeStore


class FakeGovernor:
    def __init__(
        self, *, allowed=True, max_seconds=2.0, max_memory_mb=32.0,
        permit_overrides=None, invalid_budget=None,
    ):
        self.allowed = allowed
        self.max_seconds = max_seconds
        self.max_memory_mb = max_memory_mb
        self.permit_overrides = permit_overrides or {}
        self.invalid_budget = invalid_budget or {}
        self.sessions = []
        self.requests = []

    def evaluate_session(self, runtime_context, *, resource_snapshot=None):
        self.sessions.append(runtime_context)
        return {
            "status": "bounded",
            "mode": "test_foreground",
            "budget": {
                "max_task_seconds": self.max_seconds,
                "max_task_ram_mb": self.max_memory_mb,
                "max_concurrent_tasks": 1,
                "continuous_loop_allowed": False,
                "network_allowed": False,
                "camera_capture_allowed": False,
                "microphone_capture_allowed": False,
                "android_changes_allowed": False,
                "package_installation_allowed": False,
                "project_writes_allowed": False,
                **self.invalid_budget,
            },
        }

    def evaluate_work(self, session, work_request):
        self.requests.append(work_request)
        if not self.allowed:
            return {"allowed": False, "reason": "bloqueio de teste"}
        return {
            "allowed": True,
            "permit": {
                "task_id": work_request["task_id"],
                "risk": work_request["risk"],
                "max_runtime_seconds": min(self.max_seconds, work_request["estimated_seconds"]),
                "max_memory_mb": min(self.max_memory_mb, work_request["estimated_ram_mb"]),
                "continuous_loop": False,
                "side_effects": "none",
                "execution_performed": False,
                **self.permit_overrides,
            },
        }


def _runtime_context():
    return {
        "app_foreground": True,
        "screen_interactive": True,
        "thermal_status": "normal",
        "source": "test_fixture",
    }


def make_orchestrator(tmp_path, *, dharma=None, governor=None, runtime_context_provider=True):
    store = KnowledgeStore(tmp_path / "research.sqlite3")
    cognitive = SimpleNamespace(store=store, dharma=dharma or Dharma(tmp_path))
    governor = governor or FakeGovernor()
    provider = _runtime_context if runtime_context_provider else None
    return ResearchOrchestrator(
        cognitive,
        autonomy=governor,
        runtime_context_provider=provider,
    ), store


def test_governor_admits_one_cooperative_task_and_records_events(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    seen = []

    def slow(execution_context):
        execution_context.check()
        time.sleep(0.05)
        execution_context.check()
        seen.append(True)
        return "completed"

    orchestrator.register_capability(
        "test.slow", slow, risk="local_compute", description="Tarefa limitada."
    )

    result = orchestrator.run_parallel([{
        "id": "a", "name": "slow", "capability": "test.slow",
    }])

    assert result["status"] == "completed"
    assert result["tasks"][0]["result"] == "completed"
    assert result["deadline_enforcement"] == "cooperative"
    assert result["memory_enforcement"] == "admission_only"
    assert seen == [True]
    assert len(orchestrator.autonomy.sessions) == 1
    assert len(orchestrator.autonomy.requests) == 1
    assert orchestrator.autonomy.requests[0]["estimated_ram_mb"] == 32.0
    assert len(store.list_events(10)) == 3


def test_governor_permit_must_be_bound_to_exact_task_and_risk(tmp_path):
    governor = FakeGovernor(permit_overrides={"task_id": "different-task"})
    orchestrator, _ = make_orchestrator(tmp_path, governor=governor)
    executed = []

    def task(execution_context):
        execution_context.check()
        executed.append(True)

    orchestrator.register_capability(
        "test.bound", task, risk="local_compute",
        description="Permit bound to one task.",
    )
    with pytest.raises(PermissionError, match="outra tarefa"):
        orchestrator.run_parallel([{
            "id": "expected-task", "name": "bound", "capability": "test.bound",
        }])
    assert executed == []


def test_governor_permit_rejects_non_finite_or_oversized_budgets(tmp_path):
    governor = FakeGovernor(permit_overrides={"max_runtime_seconds": float("inf")})
    orchestrator, _ = make_orchestrator(tmp_path, governor=governor)

    def task(execution_context):
        execution_context.check()

    orchestrator.register_capability(
        "test.invalid_permit", task, risk="local_compute",
        description="Permit must have finite limits.",
    )
    with pytest.raises(PermissionError, match="fora do limite"):
        orchestrator.run_parallel([{
            "id": "invalid-permit", "name": "invalid",
            "capability": "test.invalid_permit",
        }])


def test_governor_rejects_boolean_concurrency_limit(tmp_path):
    governor = FakeGovernor(invalid_budget={"max_concurrent_tasks": True})
    orchestrator, _ = make_orchestrator(tmp_path, governor=governor)

    def task(execution_context):
        execution_context.check()

    orchestrator.register_capability(
        "test.boolean_concurrency", task, risk="local_compute",
        description="Boolean must not be accepted as integer one.",
    )
    with pytest.raises(PermissionError, match="exatamente uma tarefa"):
        orchestrator.run_parallel([{
            "id": "boolean-limit", "name": "boolean",
            "capability": "test.boolean_concurrency",
        }])


def test_governor_session_must_disable_unapproved_capabilities(tmp_path):
    governor = FakeGovernor(invalid_budget={"network_allowed": True})
    orchestrator, _ = make_orchestrator(tmp_path, governor=governor)

    def task(execution_context):
        execution_context.check()

    orchestrator.register_capability(
        "test.network_budget", task, risk="local_compute",
        description="Session must not authorize network.",
    )
    with pytest.raises(PermissionError, match="network_allowed"):
        orchestrator.run_parallel([{
            "id": "network-budget", "name": "network",
            "capability": "test.network_budget",
        }])


def test_task_exception_is_reported(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    def fail(execution_context):
        execution_context.check()
        raise ValueError("expected failure")

    orchestrator.register_capability(
        "test.fail", fail, risk="local_compute", description="Falha controlada."
    )
    result = orchestrator.run_parallel([{
        "id": "bad", "name": "failure", "capability": "test.fail",
    }])

    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert result["completed"] == 0
    assert result["tasks"][0]["error"]["type"] == "ValueError"


def test_parallel_batches_are_rejected_until_independent_permits_exist(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    with pytest.raises(ValueError, match="uma tarefa por autorização"):
        orchestrator.run_parallel([
            {"id": "one", "name": "one", "capability": "missing.one"},
            {"id": "two", "name": "two", "capability": "missing.two"},
        ])
    assert store.list_events(10) == []


def test_capability_without_cooperative_context_is_rejected(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)
    orchestrator.register_capability(
        "test.legacy", lambda: 1,
        risk="read_only", description="Callable without deadline context.",
    )
    with pytest.raises(ValueError, match="execution_context"):
        orchestrator.run_parallel([{
            "id": "legacy", "name": "legacy", "capability": "test.legacy",
        }])


def test_unknown_or_background_runtime_context_fails_closed(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    executed = []

    def task(execution_context):
        execution_context.check()
        executed.append(True)

    orchestrator.register_capability(
        "test.foreground", task, risk="local_compute",
        description="Task requiring visible foreground.",
    )
    with pytest.raises(PermissionError, match="primeiro plano"):
        orchestrator.run_parallel([{
            "id": "background", "name": "background",
            "capability": "test.foreground",
        }], runtime_context={
            "app_foreground": None,
            "screen_interactive": True,
            "thermal_status": "unknown",
        })
    assert executed == []
    assert store.list_events(10) == []


def test_governor_denial_prevents_execution(tmp_path):
    governor = FakeGovernor(allowed=False)
    orchestrator, store = make_orchestrator(tmp_path, governor=governor)
    executed = []

    def task(execution_context):
        execution_context.check()
        executed.append(True)

    orchestrator.register_capability(
        "test.denied", task, risk="local_compute",
        description="Task blocked by Governor.",
    )
    with pytest.raises(PermissionError, match="bloqueou a tarefa"):
        orchestrator.run_parallel([{
            "id": "denied", "name": "denied", "capability": "test.denied",
        }])
    assert executed == []
    assert store.list_events(10) == []


def test_governor_is_mandatory_for_execution(tmp_path):
    store = KnowledgeStore(tmp_path / "no-governor.sqlite3")
    cognitive = SimpleNamespace(store=store, dharma=Dharma(tmp_path))
    orchestrator = ResearchOrchestrator(cognitive)
    with pytest.raises(RuntimeError, match="AutonomyGovernor obrigatório"):
        orchestrator.run_parallel([])


def test_dharma_denial_blocks_execution(tmp_path):
    from agent.dharma import Decision

    class DenyLocalCompute(Dharma):
        def evaluate(self, action, target="", context=None):
            if action == "local_compute":
                return Decision(
                    False, True, "blocked by test", 70, "test-denied", True
                )
            return super().evaluate(action, target, context)

    orchestrator, store = make_orchestrator(tmp_path, dharma=DenyLocalCompute(tmp_path))
    executed = []

    def task(execution_context):
        execution_context.check()
        executed.append(True)

    orchestrator.register_capability(
        "test.must_not_run",
        task,
        risk="local_compute",
        description="Execução que deve ser bloqueada.",
    )

    with pytest.raises(PermissionError, match="blocked by test"):
        orchestrator.run_parallel([{
            "id": "x",
            "name": "must not run",
            "capability": "test.must_not_run",
        }])

    assert executed == []
    assert store.list_events(10) == []


def test_initiative_plan_requires_approval_and_never_dispatches_tools(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    candidate = {
        "candidate_id": "inquiry:" + "a" * 24,
        "kind": "self_inquiry",
        "title": "Investigar lacuna: persistência",
        "description": "Como validar recuperação após reinício?",
        "source": "persisted_self_inquiry",
        "evidence": {"observation_ids": [7], "epistemic_state": "open_question_not_conclusion"},
    }
    orchestrator.cognitive.review_initiatives = lambda: {
        "status": "reviewed",
        "candidates": [candidate],
    }
    before = store.counts()

    with pytest.raises(PermissionError, match="aprovação explícita"):
        orchestrator.prepare_initiative_plan(candidate["candidate_id"])
    assert store.counts() == before
    assert store.load_memories() == {}

    prepared = orchestrator.prepare_initiative_plan(
        candidate["candidate_id"], approved=True
    )
    assert prepared["status"] == "prepared"
    plan = prepared["plan"]
    assert plan["schema"] == "mahoraga.research_plan"
    assert plan["research_question"] == candidate["description"]
    assert plan["evidence"]["observation_ids"] == [7]
    assert len(plan["stages"]) == 5
    assert plan["execution_authorized"] is False
    assert plan["execution_performed"] is False
    assert plan["governance"]["tool_dispatch_performed"] is False
    assert plan["governance"]["network_access_enabled"] is False
    assert prepared["tool_dispatch_performed"] is False

    repeated = orchestrator.prepare_initiative_plan(
        candidate["candidate_id"], approved=True
    )
    assert repeated["status"] == "already_prepared"
    assert repeated["plan"]["plan_id"] == plan["plan_id"]
    assert len(store.load_memories()) == 1
    assert len(store.list_events(event_type="memory.saved")) == 1


def test_initiative_plan_rejects_stale_candidate_without_persisting(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    orchestrator.cognitive.review_initiatives = lambda: {
        "status": "reviewed",
        "candidates": [],
    }

    with pytest.raises(ValueError, match="não encontrada"):
        orchestrator.prepare_initiative_plan("stale-candidate", approved=True)

    assert store.load_memories() == {}
    assert store.list_events(limit=20) == []



def test_initiative_plan_rejects_oversized_or_non_json_evidence(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    candidate = {
        "candidate_id": "experience:" + "c" * 24,
        "kind": "experience_pattern",
        "title": "Avaliar padrão",
        "description": "A hipótese precisa de evidência limitada.",
        "source": "adaptive_learning",
        "evidence": {"payload": "x" * 9000},
    }
    orchestrator.cognitive.review_initiatives = lambda: {
        "status": "reviewed",
        "candidates": [candidate],
    }

    with pytest.raises(ValueError, match="8192 bytes"):
        orchestrator.prepare_initiative_plan(
            candidate["candidate_id"], approved=True
        )
    assert store.get_memory(
        "research_plan:" + "research-" + __import__("hashlib").sha256(
            candidate["candidate_id"].encode("utf-8")
        ).hexdigest()[:24]
    ) is None

    candidate["evidence"] = {"unsupported": object()}
    with pytest.raises(ValueError, match="JSON válida"):
        orchestrator.prepare_initiative_plan(
            candidate["candidate_id"], approved=True
        )
    assert store.load_memories() == {}
