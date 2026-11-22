import pytest
from pathlib import Path

from agent.capability_adapters import ReadOnlyCapabilityAdapters
from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore


class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


@pytest.fixture
def capability_environment(tmp_path):
    import shutil

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    manifest_source = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "capability_manifest.json"
    )
    shutil.copy2(
        manifest_source,
        config_dir / "capability_manifest.json",
    )

    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    core = IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=FakeHardware(),
    )
    adapters = ReadOnlyCapabilityAdapters(core)
    return core, store, adapters


def test_builds_exactly_seven_declared_bindings(capability_environment):
    core, store, adapters = capability_environment

    bindings = adapters.build_bindings()

    assert set(bindings) == set(adapters.CAPABILITY_IDS)
    assert len(bindings) == 7
    assert all(callable(function) for function in bindings.values())


def test_all_seven_adapters_return_structured_results(
    capability_environment,
):
    core, store, adapters = capability_environment
    bindings = adapters.build_bindings()

    for capability_id, function in bindings.items():
        result = function()
        assert isinstance(result, dict), capability_id


def test_shared_components_are_preserved(capability_environment):
    core, store, adapters = capability_environment

    assert core.cognitive.store is store
    assert core.knowledge.store is store
    assert core.introspection.store is store
    assert core.introspection.hardware is core.hardware
    assert core.introspection.tools is core.tools
    assert core.research_orchestrator.store is store


def test_introspection_adapters_never_persist(capability_environment):
    core, store, adapters = capability_environment
    bindings = adapters.build_bindings()

    before_counts = store.counts()
    before_events = store.list_events(limit=10000)
    before_experiments = store.list_experiments(limit=10000)

    model = bindings["introspection.self_model_read"]()
    audit = bindings["introspection.capability_audit"]()

    assert isinstance(model, dict)
    assert isinstance(audit, dict)

    assert store.counts() == before_counts
    assert store.list_events(limit=10000) == before_events
    assert store.list_experiments(limit=10000) == before_experiments

    with pytest.raises(TypeError):
        bindings["introspection.self_model_read"](persist=True)

    with pytest.raises(TypeError):
        bindings["introspection.capability_audit"](persist=True)


def test_binding_construction_does_not_register_or_activate(
    capability_environment,
):
    core, store, adapters = capability_environment

    bindings = adapters.build_bindings()

    assert core.research_orchestrator._capabilities == {}
    assert store.list_capabilities() == []
    assert len(bindings) == 7


def test_database_integrity_remains_valid(capability_environment):
    core, store, adapters = capability_environment

    bindings = adapters.build_bindings()
    for function in bindings.values():
        function()

    assert store.integrity_check() == "ok"


def test_disabled_manifest_capabilities_reject_runtime_registration(
    capability_environment,
):
    core, store, adapters = capability_environment
    bindings = adapters.build_bindings()

    sync_result = core.research_orchestrator.sync_manifest_catalog()
    expected_manifest_count = len(core.capability_manifest.definitions())
    assert sync_result["inserted_count"] == expected_manifest_count

    catalog_before = store.list_capabilities()
    assert len(catalog_before) == expected_manifest_count
    assert all(item["enabled"] is False for item in catalog_before)

    for capability_id, function in bindings.items():
        with pytest.raises(PermissionError, match="desabilitada"):
            core.research_orchestrator.register_capability(
                capability_id,
                function,
                risk="read_only",
                description=f"Teste controlado de {capability_id}.",
            )

    status = core.research_orchestrator.status()
    assert status["registered_capabilities"] == []
    assert status["runtime_bound_count"] == 0
    assert store.list_capabilities() == catalog_before
    assert store.integrity_check() == "ok"


class GovernedFakeHardware(FakeHardware):
    def runtime_context(self):
        return {
            "app_foreground": True,
            "screen_interactive": True,
            "thermal_status": "normal",
            "source": "test_fixture",
        }

    def battery(self):
        return {"termux_api": {"data": {"percentage": 90, "status": "charging"}}}

    def memory(self):
        return {"values": {"MemAvailable": {"mb": 4096}}}

    def storage(self):
        return {"project": {"free_bytes": 8 * 1024 * 1024 * 1024}}

    def thermal(self):
        return {"status": "normal"}


def test_memory_history_adapter_exposes_metadata_without_private_payloads(
    capability_environment,
):
    core, store, adapters = capability_environment
    store.save_memory(
        "private:record",
        {"secret": "private-memory-payload"},
        metadata={"kind": "private"},
    )
    store.record_event(
        "private.event",
        {"secret": "private-event-payload"},
    )

    result = adapters.memory_history_read()

    assert result["payloads_exposed"] is False
    assert result["memory_count"] == 1
    assert result["memory_window_truncated"] is False
    assert result["event_window_truncated"] is False
    assert result["memory_catalog"][0]["key"] == "private:record"
    assert set(result["memory_catalog"][0]) == {
        "key", "created_at", "updated_at"
    }
    assert set(result["events"][0]) == {
        "id", "event_type", "severity", "created_at"
    }
    serialized = repr(result)
    assert "private-memory-payload" not in serialized
    assert "private-event-payload" not in serialized


def test_governed_bindings_require_execution_context_and_check_around_call(
    capability_environment,
):
    core, store, adapters = capability_environment
    bindings = adapters.build_governed_bindings()
    calls = []

    class Context:
        def check(self):
            calls.append("check")

    with pytest.raises(TypeError):
        bindings["hardware.snapshot"]()

    result = bindings["hardware.snapshot"](execution_context=Context())

    assert result["android"]["model"] == "test-device"
    assert calls == ["check", "check"]


def test_disabled_manifest_blocks_explicit_read_only_registration(
    capability_environment,
):
    core, store, adapters = capability_environment

    with pytest.raises(PermissionError, match="desabilitada"):
        core.register_read_only_capability("hardware.snapshot")

    assert core.research_orchestrator._capabilities == {}
    assert store.list_capabilities() == []


def test_enabled_read_only_adapter_registers_and_runs_through_governor(tmp_path):
    import json
    import shutil

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1] / "config" / "capability_manifest.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    target = next(item for item in document["capabilities"] if item["id"] == "hardware.snapshot")
    target["enabled"] = True
    (config_dir / "capability_manifest.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    store = KnowledgeStore(tmp_path / "enabled-adapter.sqlite3")
    core = IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=GovernedFakeHardware(),
    )

    registration = core.register_read_only_capability("hardware.snapshot")

    assert registration["status"] == "registered"
    assert registration["execution_performed"] is False
    assert registration["registration"]["registered"] is True
    assert core.research_orchestrator.status()["runtime_bound_count"] == 1

    result = core.research_orchestrator.run_parallel([{
        "id": "hardware-snapshot-001",
        "name": "Snapshot de hardware somente de leitura",
        "capability": "hardware.snapshot",
    }])

    assert result["status"] == "completed"
    assert result["tasks"][0]["result"]["android"]["model"] == "test-device"
    assert result["resource_session"]["status"] == "bounded"
    assert result["deadline_enforcement"] == "cooperative"

def test_cognition_context_adapter_is_metadata_only(capability_environment):
    core, store, adapters = capability_environment
    store.save_memory(
        "context:private",
        {"secret": "private-cognition-memory"},
        metadata={"kind": "private"},
    )
    store.record_event(
        "context.private",
        {"secret": "private-cognition-event"},
    )

    result = adapters.cognition_context_review(topic="test")

    assert result["status"] == "metadata_reviewed"
    assert result["payloads_exposed"] is False
    assert result["memory_window_truncated"] is False
    assert result["event_window_truncated"] is False
    assert "private-cognition-memory" not in repr(result)
    assert "private-cognition-event" not in repr(result)
    assert "memory_catalog" in result
    assert "event_catalog" in result


def test_adapter_limits_and_resource_estimates_are_declared(capability_environment):
    core, store, adapters = capability_environment

    with pytest.raises(ValueError, match="chunk_limit"):
        adapters.knowledge_catalog_read(chunk_limit=201)
    with pytest.raises(ValueError, match="event_limit"):
        adapters.memory_history_read(event_limit=201)
    with pytest.raises(ValueError, match="event_limit"):
        adapters.cognition_context_review(event_limit=101)
    with pytest.raises(ValueError, match="limit_experiments"):
        adapters.introspection_capability_audit(limit_experiments=101)

    for capability in core.capability_manifest.definitions():
        if capability["id"] not in adapters.CAPABILITY_IDS:
            continue
        requirements = capability["resource_requirements"]
        assert 0 < requirements["estimated_runtime_seconds"] <= core.research_orchestrator.MAX_CAPABILITY_SECONDS
        assert 0 < requirements["estimated_ram_mb"] <= core.research_orchestrator.MAX_CAPABILITY_MEMORY_MB

def test_enabled_manifest_cannot_override_disabled_persistent_catalog(tmp_path):
    import json

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1] / "config" / "capability_manifest.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    target = next(item for item in document["capabilities"] if item["id"] == "hardware.snapshot")
    target["enabled"] = True
    (config_dir / "capability_manifest.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    store = KnowledgeStore(tmp_path / "stale-catalog.sqlite3")
    store.upsert_capability("hardware.snapshot", {
        "name": "Leitura do hardware",
        "purpose": "Registro persistente previamente desabilitado.",
        "risk": "read_only",
        "maturity_state": "implemented",
        "enabled": False,
    })
    core = IntegratedCore(root=tmp_path, store=store, hardware=GovernedFakeHardware())

    with pytest.raises(PermissionError, match="diverge"):
        core.register_read_only_capability("hardware.snapshot")

    assert core.research_orchestrator._capabilities == {}
    entry = next(
        item for item in store.list_capabilities()
        if item["capability_id"] == "hardware.snapshot"
    )
    assert entry["enabled"] is False


def test_read_only_registration_rejects_unknown_adapter_identifier(capability_environment):
    core, store, adapters = capability_environment

    with pytest.raises(ValueError, match="não pertence"):
        core.register_read_only_capability("shell.execute")

    assert core.research_orchestrator._capabilities == {}

