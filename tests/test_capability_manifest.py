import json
from types import SimpleNamespace

import pytest

from agent.capability_manifest import CapabilityManifest
from agent.dharma import Dharma
from agent.research_orchestrator import ResearchOrchestrator
from agent.store import KnowledgeStore


def make_definition(
    capability_id="math.add",
    risk="local_compute",
    enabled=True,
):
    return {
        "id": capability_id,
        "name": "Soma matemática",
        "purpose": "Somar dois números localmente.",
        "description": "Capacidade de teste.",
        "version": "1.0.0",
        "risk": risk,
        "maturity_state": "implemented",
        "source_module": "tests",
        "operations": ["add"],
        "inputs": {"a": "number", "b": "number"},
        "outputs": {"result": "number"},
        "dependencies": [],
        "tools": [],
        "limitations": ["Somente números."],
        "resource_requirements": {"cpu": "low"},
        "validation": {"tests_passed": 0},
        "enabled": enabled,
        "metadata": {},
    }


def write_manifest(path, capabilities):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "schema": "mahoraga.capability_manifest",
            "version": "1.0.0",
            "capabilities": capabilities,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


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


def runtime_context():
    return {
        "app_foreground": True,
        "screen_interactive": True,
        "thermal_status": "normal",
    }


def make_system(tmp_path, capabilities=None, *, governed=True):
    store = KnowledgeStore(tmp_path / "manifest_test.sqlite3")
    manifest_path = tmp_path / "config" / "capability_manifest.json"
    write_manifest(
        manifest_path,
        capabilities if capabilities is not None else [make_definition()],
    )
    manifest = CapabilityManifest(manifest_path)
    cognitive = SimpleNamespace(
        store=store,
        dharma=Dharma(tmp_path),
    )
    orchestrator = ResearchOrchestrator(
        cognitive,
        capability_manifest=manifest,
        autonomy=FakeGovernor() if governed else None,
        runtime_context_provider=runtime_context if governed else None,
    )
    return orchestrator, manifest, store


def test_manifest_loads_without_executable_bindings(tmp_path):
    orchestrator, manifest, _ = make_system(tmp_path)

    assert manifest.valid is True
    assert manifest.status()["declared_count"] == 1
    assert manifest.status()["executable_bindings"] == 0
    assert manifest.status()["code_loading_enabled"] is False
    assert orchestrator.status()["manifest"]["valid"] is True
    assert orchestrator.status()["registered_capabilities"] == []


def test_manifest_sync_inserts_metadata_only(tmp_path):
    orchestrator, manifest, store = make_system(tmp_path)

    result = orchestrator.sync_manifest_catalog()

    assert result["inserted"] == ["math.add"]
    assert result["inserted_count"] == 1
    assert result["executables_loaded"] == 0

    catalog = store.list_capabilities()
    assert len(catalog) == 1
    assert catalog[0]["capability_id"] == "math.add"
    assert catalog[0]["maturity_state"] == "implemented"
    assert orchestrator.status()["runtime_bound_count"] == 0
    assert manifest.status()["executable_bindings"] == 0


def test_registration_requires_explicit_manifest_sync(tmp_path):
    orchestrator, _, _ = make_system(tmp_path)

    def add(a, b, execution_context):
        execution_context.check()
        return a + b

    with pytest.raises(PermissionError, match="não sincronizada"):
        orchestrator.register_capability(
            "math.add",
            add,
            risk="local_compute",
            description="Soma dois números.",
        )

    assert orchestrator.status()["registered_capabilities"] == []


def test_explicit_sync_then_binding_allows_execution(tmp_path):
    orchestrator, _, _ = make_system(tmp_path)
    orchestrator.sync_manifest_catalog()

    def add(a, b):
        return a + b

    orchestrator.register_capability(
        "math.add",
        add,
        risk="local_compute",
        description="Soma dois números.",
    )

    result = orchestrator.run_parallel([{
        "id": "sum-1",
        "name": "Soma",
        "capability": "math.add",
        "args": [4, 7],
    }])

    assert result["status"] == "completed"
    assert result["tasks"][0]["result"] == 11
    assert orchestrator.status()["runtime_bound_count"] == 1


def test_disabled_manifest_capability_cannot_be_bound(tmp_path):
    orchestrator, _, _ = make_system(
        tmp_path,
        [make_definition(enabled=False)],
    )
    orchestrator.sync_manifest_catalog()

    with pytest.raises(PermissionError, match="desabilitada"):
        orchestrator.register_capability(
            "math.add",
            lambda a, b: a + b,
            risk="local_compute",
            description="Soma dois números.",
        )


def test_manifest_risk_mismatch_cannot_be_bound(tmp_path):
    orchestrator, _, _ = make_system(
        tmp_path,
        [make_definition(risk="read_only")],
    )
    orchestrator.sync_manifest_catalog()

    with pytest.raises(PermissionError, match="Risco incompatível"):
        orchestrator.register_capability(
            "math.add",
            lambda a, b: a + b,
            risk="local_compute",
            description="Soma dois números.",
        )


def test_sync_preserves_existing_evidence_and_maturity(tmp_path):
    orchestrator, _, store = make_system(tmp_path)

    store.upsert_capability("math.add", {
        "name": "Registro anterior",
        "purpose": "Evidência previamente armazenada.",
        "risk": "local_compute",
        "maturity_state": "tested_individually",
        "enabled": True,
        "validation": {
            "tests_passed": 17,
            "evidence": "execução anterior",
        },
    })

    result = orchestrator.sync_manifest_catalog()

    assert result["inserted_count"] == 0
    assert result["preserved_existing"] == ["math.add"]
    assert result["conflict_count"] == 0

    current = store.list_capabilities()[0]
    assert current["name"] == "Registro anterior"
    assert current["maturity_state"] == "tested_individually"
    assert current["validation"]["tests_passed"] == 17


def test_manifest_rejects_nested_executable_content(tmp_path):
    definition = make_definition()
    definition["metadata"] = {
        "nested": {"function": "malicious"}
    }

    path = tmp_path / "config" / "capability_manifest.json"
    write_manifest(path, [definition])
    manifest = CapabilityManifest(path)

    assert manifest.valid is False

    store = KnowledgeStore(tmp_path / "invalid_manifest.sqlite3")
    with pytest.raises(RuntimeError, match="Manifesto inválido"):
        manifest.sync_to_catalog(store)
