from types import SimpleNamespace

import pytest

from agent.dharma import Dharma
from agent.research_orchestrator import ResearchOrchestrator
from agent.store import KnowledgeStore


class FakeGovernor:
    def evaluate_session(self, runtime_context, *, resource_snapshot=None):
        assert runtime_context["app_foreground"] is True
        assert runtime_context["screen_interactive"] is True
        return {
            "status": "bounded",
            "mode": "test",
            "budget": {
                "max_task_seconds": 5.0,
                "max_task_ram_mb": 64.0,
                "max_concurrent_tasks": 1,
                "continuous_loop_allowed": False,
                "network_allowed": False,
                "camera_capture_allowed": False,
                "microphone_capture_allowed": False,
                "android_changes_allowed": False,
                "package_installation_allowed": False,
                "project_writes_allowed": False,
            },
        }

    def evaluate_work(self, session, work_request):
        return {
            "allowed": True,
            "permit": {
                "task_id": work_request["task_id"],
                "risk": work_request["risk"],
                "max_runtime_seconds": min(5.0, work_request["estimated_seconds"]),
                "max_memory_mb": min(64.0, work_request["estimated_ram_mb"]),
                "continuous_loop": False,
                "side_effects": "none",
                "execution_performed": False,
            },
        }


def _runtime_context():
    return {
        "app_foreground": True,
        "screen_interactive": True,
        "thermal_status": "normal",
    }


def make_orchestrator(tmp_path, *, dharma=None):
    store = KnowledgeStore(tmp_path / "capabilities.sqlite3")
    cognitive = SimpleNamespace(store=store, dharma=dharma or Dharma(tmp_path))
    return ResearchOrchestrator(
        cognitive,
        autonomy=FakeGovernor(),
        runtime_context_provider=_runtime_context,
    ), store


def test_registered_capability_executes_by_identifier(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    def add(a, b, execution_context):
        execution_context.check()
        return a + b

    orchestrator.register_capability(
        "math.add",
        add,
        risk="local_compute",
        description="Soma dois números.",
    )

    result = orchestrator.run_parallel([
        {
            "id": "sum-1",
            "name": "Soma",
            "capability": "math.add",
            "args": [4, 7],
        }
    ])

    assert result["status"] == "completed"
    assert result["tasks"][0]["result"] == 11
    assert result["tasks"][0]["risk"] == "local_compute"


def test_unregistered_capability_is_rejected(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    with pytest.raises(ValueError, match="não registrada"):
        orchestrator.run_parallel([
            {
                "id": "unknown-1",
                "name": "Desconhecida",
                "capability": "unknown.execute",
            }
        ])


def test_arbitrary_task_function_is_rejected(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)
    executed = []

    with pytest.raises(ValueError, match="função"):
        orchestrator.run_parallel([
            {
                "id": "arbitrary-1",
                "name": "Função arbitrária",
                "function": lambda: executed.append(True),
            }
        ])

    assert executed == []


def test_task_cannot_downgrade_registered_risk(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    def compute(execution_context):
        execution_context.check()
        return 42

    orchestrator.register_capability(
        "compute.heavy",
        compute,
        risk="local_compute",
        description="Cálculo local.",
    )

    result = orchestrator.run_parallel([
        {
            "id": "compute-1",
            "name": "Cálculo",
            "capability": "compute.heavy",
            "risk": "read_only",
        }
    ])

    assert result["tasks"][0]["risk"] == "local_compute"


def test_duplicate_capability_registration_is_rejected(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    orchestrator.register_capability(
        "math.add",
        lambda a, b: a + b,
        risk="local_compute",
        description="Soma.",
    )

    with pytest.raises(ValueError, match="já registrada"):
        orchestrator.register_capability(
            "math.add",
            lambda: 0,
            risk="read_only",
            description="Substituição não autorizada.",
        )


def test_async_capability_is_rejected(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    async def asynchronous_task():
        return 1

    with pytest.raises(ValueError, match="assíncronas"):
        orchestrator.register_capability(
            "test.async",
            asynchronous_task,
            risk="read_only",
            description="Teste assíncrono.",
        )


def test_denied_capability_prevents_execution(tmp_path):
    from agent.dharma import Decision

    class SelectiveDharma(Dharma):
        def evaluate(self, action, target="", context=None):
            if action == "local_compute":
                return Decision(
                    False, True, "Bloqueio simulado para teste.",
                    65, "approval-required", True,
                )
            return super().evaluate(action, target, context)

    orchestrator, store = make_orchestrator(
        tmp_path, dharma=SelectiveDharma(tmp_path)
    )
    executed = []

    def compute(execution_context):
        execution_context.check()
        executed.append("compute")

    orchestrator.register_capability(
        "test.compute",
        compute,
        risk="local_compute",
        description="Capacidade computacional.",
    )

    with pytest.raises(PermissionError, match="Bloqueio simulado"):
        orchestrator.run_parallel([
            {"id": "compute", "name": "Cálculo", "capability": "test.compute"},
        ])

    assert executed == []
    assert store.list_events(10) == []


def _catalog_definition(capability_id, *, risk="read_only",
                        maturity_state="implemented", enabled=True):
    return {
        "name": capability_id,
        "purpose": "Definição de teste do catálogo.",
        "description": "Metadados persistentes de teste.",
        "version": "0.1.0",
        "risk": risk,
        "maturity_state": maturity_state,
        "source_module": "tests.test_research_capabilities",
        "operations": ["sample_operation"],
        "inputs": {},
        "outputs": {},
        "dependencies": [],
        "tools": [],
        "limitations": ["Não contém código executável."],
        "resource_requirements": {},
        "validation": {"evidence": "fixture de teste"},
        "enabled": enabled,
        "metadata": {"origin": "test_fixture"},
    }


def test_registration_persists_metadata_without_executable_code(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)

    def sample_operation(value):
        return value * 2

    orchestrator.register_capability(
        "test.persisted", sample_operation,
        risk="read_only",
        description="Capacidade persistida para teste.",
    )

    catalog = store.list_capabilities()
    assert len(catalog) == 1
    item = catalog[0]
    assert item["capability_id"] == "test.persisted"
    assert item["maturity_state"] == "implemented"
    assert item["enabled"] is True
    assert item["validation"]["registration_verified"] is True
    assert item["validation"]["individual_tests_passed"] is False
    assert item["validation"]["integration_tests_passed"] is False
    assert item["validation"]["real_world_validated"] is False
    assert item["metadata"]["binding_type"] == "explicit_trusted_runtime_registration"
    assert "function" not in item
    assert "callable" not in item
    assert "source_code" not in item


def test_catalog_survives_reopen_without_restoring_runtime_callable(tmp_path):
    database_path = tmp_path / "capabilities.sqlite3"
    store = KnowledgeStore(database_path)
    first = ResearchOrchestrator(
        SimpleNamespace(store=store, dharma=Dharma(tmp_path)),
        autonomy=FakeGovernor(),
        runtime_context_provider=_runtime_context,
    )
    first.register_capability(
        "test.reopen", lambda: "não deve ser restaurada",
        risk="read_only",
        description="Capacidade para teste de reabertura.",
    )

    reopened_store = KnowledgeStore(database_path)
    reopened = ResearchOrchestrator(
        SimpleNamespace(
            store=reopened_store,
            dharma=Dharma(tmp_path),
        ),
        autonomy=FakeGovernor(),
        runtime_context_provider=_runtime_context,
    )

    status = reopened.status()
    assert status["catalog_count"] == 1
    assert status["runtime_bound_count"] == 0
    assert status["unbound_catalog_count"] == 1
    assert status["persistent_capabilities"][0]["runtime_bound"] is False
    assert status["registered_capabilities"] == []

    with pytest.raises(ValueError, match="não registrada"):
        reopened.run_parallel([{
            "id": "reopen-1",
            "name": "Execução sem vínculo",
            "capability": "test.reopen",
        }])


def test_disabled_catalog_capability_cannot_be_bound(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    store.upsert_capability(
        "test.disabled",
        _catalog_definition("test.disabled", enabled=False),
    )

    with pytest.raises(PermissionError, match="desabilitada"):
        orchestrator.register_capability(
            "test.disabled", lambda: 1,
            risk="read_only",
            description="Tentativa de vínculo de capacidade desabilitada.",
        )

    assert orchestrator.status()["registered_capabilities"] == []
    assert store.list_capabilities()[0]["enabled"] is False


def test_catalog_risk_mismatch_preserves_existing_metadata(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    original = _catalog_definition(
        "test.risk_mismatch",
        risk="read_only",
        maturity_state="tested_individually",
    )
    original["description"] = "Descrição original preservada."
    original["validation"] = {
        "individual_tests_passed": True,
        "evidence": "test-123",
    }
    store.upsert_capability("test.risk_mismatch", original)

    with pytest.raises(PermissionError, match="Risco incompatível"):
        orchestrator.register_capability(
            "test.risk_mismatch", lambda: 1,
            risk="local_compute",
            description="Tentativa com risco divergente.",
        )

    item = store.list_capabilities()[0]
    assert item["risk"] == "read_only"
    assert item["maturity_state"] == "tested_individually"
    assert item["description"] == "Descrição original preservada."
    assert item["validation"] == {
        "individual_tests_passed": True,
        "evidence": "test-123",
    }
    assert orchestrator.status()["registered_capabilities"] == []


def test_persistence_failure_does_not_create_runtime_binding(tmp_path, monkeypatch):
    orchestrator, store = make_orchestrator(tmp_path)

    def fail_persistence(*args, **kwargs):
        raise RuntimeError("falha simulada de persistência")

    monkeypatch.setattr(store, "upsert_capability", fail_persistence)

    with pytest.raises(RuntimeError, match="falha simulada"):
        orchestrator.register_capability(
            "test.persistence_failure", lambda: 1,
            risk="read_only",
            description="Teste de falha de persistência.",
        )

    status = orchestrator.status()
    assert status["registered_capabilities"] == []
    assert status["catalog_count"] == 0
    assert status["runtime_bound_count"] == 0


def test_registration_rejects_non_ascii_identifier_and_non_string_risk(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    with pytest.raises(ValueError, match="Identificador"):
        orchestrator.register_capability(
            "matemática.operation", lambda: 1,
            risk="read_only",
            description="Identificador não ASCII.",
        )

    with pytest.raises(PermissionError, match="Categoria de risco"):
        orchestrator.register_capability(
            "test.invalid_risk", lambda: 1,
            risk=["read_only"],
            description="Risco com tipo inválido.",
        )

    assert orchestrator.status()["registered_capabilities"] == []

