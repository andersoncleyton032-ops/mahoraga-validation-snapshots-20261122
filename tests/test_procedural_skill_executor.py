import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.capability_adapters import ReadOnlyCapabilityAdapters
from agent.capability_manifest import CapabilityManifest
from agent.dharma import Dharma
from agent.integration_core import IntegratedCore
from agent.procedural_skill_executor import (
    ProceduralSkillExecutionError,
    ProceduralSkillExecutor,
)
from agent.research_orchestrator import ResearchOrchestrator
from agent.store import KnowledgeStore


class FakeRegistry:
    valid = True

    def __init__(self, *, planned=True, capability_seconds=1, capability_ram=16):
        self.skill = {
            "id": "test.system_audit",
            "version": "1.0.0",
            "risk": "read_only",
            "resource_budget": {
                "max_runtime_seconds": 8,
                "max_ram_mb": 64,
                "max_steps": 2,
            },
            "output_schema": {
                "report": {"type": "object", "required": True, "description": "Report"}
            },
            "expected_artifacts": ["audit_report"],
            "provenance": {
                "source": "test fixture",
                "license": "internal",
                "version": "1.0.0",
            },
        }
        self.steps = [
            {
                "id": "hardware",
                "capability_id": "hardware.snapshot",
                "purpose": "Read hardware",
                "input_bindings": {},
                "checkpoint_required": True,
            },
            {
                "id": "audit",
                "capability_id": "introspection.capability_audit",
                "purpose": "Audit capabilities",
                "input_bindings": {"scope": "input.scope"},
                "checkpoint_required": True,
            },
        ]
        self.planned = planned
        self.capability_seconds = capability_seconds
        self.capability_ram = capability_ram
        self.capability_manifest = SimpleNamespace(get=self.get_capability)

    def get_capability(self, capability_id):
        return {
            "enabled": True,
            "resource_requirements": {
                "estimated_runtime_seconds": self.capability_seconds,
                "estimated_ram_mb": self.capability_ram,
            },
        }

    def get(self, skill_id):
        return dict(self.skill) if skill_id == self.skill["id"] else None

    def plan(self, skill_id, inputs=None):
        if not self.planned:
            return {
                "status": "blocked",
                "steps": [],
                "readiness": {"ready": False, "blockers": ["skill_disabled"]},
            }
        return {
            "status": "planned",
            "steps": self.steps,
            "readiness": {"ready": True, "blockers": []},
        }

    @staticmethod
    def _validate_json_value(value):
        json.dumps(value, ensure_ascii=False, allow_nan=False)


class FakeAdapters:
    def __init__(self, status="registered"):
        self.status = status
        self.calls = 0

    def register_enabled(self):
        self.calls += 1
        return {
            "status": self.status,
            "registered": ["hardware.snapshot"],
            "blockers": [],
            "execution_performed": False,
        }


class FakeOrchestrator:
    def __init__(self, *, fail_at=None, invalid_receipt=False):
        self.calls = []
        self.fail_at = fail_at
        self.invalid_receipt = invalid_receipt

    def run_parallel(self, tasks, **kwargs):
        self.calls.append((tasks, kwargs))
        index = len(self.calls)
        task = tasks[0]
        if self.fail_at == index:
            return {
                "status": "failed",
                "total": 1,
                "completed": 0,
                "failed": 1,
                "tasks": [{
                    "id": task["id"],
                    "status": "failed",
                    "error": {"type": "RuntimeError", "message": "fixture failure"},
                    "result": None,
                }],
                "execution_performed": True,
                "resource_session": {"checkpoint_sequence": 1},
            }
        if self.invalid_receipt:
            return {
                "status": "completed",
                "total": 1,
                "completed": 1,
                "failed": 0,
                "tasks": [{
                    "id": "wrong-task-id",
                    "status": "completed",
                    "error": None,
                    "result": {"unexpected": True},
                }],
                "execution_performed": True,
                "resource_session": {"checkpoint_sequence": 1},
            }
        result = (
            {"hardware": "available"}
            if index == 1
            else {"scope": task["kwargs"].get("scope"), "audited": True}
        )
        return {
            "status": "completed",
            "total": 1,
            "completed": 1,
            "failed": 0,
            "tasks": [{
                "id": task["id"],
                "status": "completed",
                "error": None,
                "result": result,
            }],
            "execution_performed": True,
            "resource_session": {"checkpoint_sequence": 1},
        }


class FakeStore:
    def __init__(self):
        self.events = []

    def record_event(self, event_type, payload, severity="info"):
        self.events.append({
            "event_type": event_type,
            "payload": payload,
            "severity": severity,
        })
        return len(self.events)


def make_executor(*, planned=True, orchestrator=None, binding_status="registered",
                  capability_seconds=1, capability_ram=16):
    registry = FakeRegistry(
        planned=planned,
        capability_seconds=capability_seconds,
        capability_ram=capability_ram,
    )
    adapters = FakeAdapters(binding_status)
    runner = orchestrator or FakeOrchestrator()
    store = FakeStore()
    return (
        ProceduralSkillExecutor(registry, adapters, runner, store),
        registry,
        adapters,
        runner,
        store,
    )


def test_executor_runs_ordered_steps_with_resolved_inputs_and_audit_receipts():
    executor, _, adapters, orchestrator, store = make_executor()

    result = executor.execute(
        "test.system_audit",
        {"scope": "hardware"},
        run_id="run-001",
        runtime_context={"app_foreground": True, "screen_interactive": True},
    )

    assert result["status"] == "completed"
    assert result["execution_performed"] is True
    assert result["tool_dispatch_performed"] is False
    assert len(orchestrator.calls) == 2
    assert orchestrator.calls[0][0][0]["capability"] == "hardware.snapshot"
    assert orchestrator.calls[1][0][0]["kwargs"] == {"scope": "hardware"}
    assert orchestrator.calls[0][1]["work_mode"] == "foreground"
    assert [item["event_type"] for item in store.events] == [
        "procedural_skill.started",
        "procedural_skill.step.completed",
        "procedural_skill.step.completed",
        "procedural_skill.completed",
    ]
    assert adapters.calls == 1


def test_executor_fails_closed_when_readiness_plan_is_blocked():
    executor, _, _, orchestrator, store = make_executor(planned=False)

    result = executor.execute("test.system_audit", run_id="blocked-001")

    assert result["status"] == "blocked"
    assert result["execution_performed"] is False
    assert orchestrator.calls == []
    assert store.events[-1]["event_type"] == "procedural_skill.blocked"


def test_executor_preserves_completed_steps_when_a_later_step_fails():
    executor, _, _, orchestrator, store = make_executor(
        orchestrator=FakeOrchestrator(fail_at=2)
    )

    result = executor.execute("test.system_audit", run_id="partial-001")

    assert result["status"] == "failed"
    assert result["completed_steps"] == ["hardware"]
    assert result["partial_results"]["hardware"] == {"hardware": "available"}
    assert result["failed_step"] == "audit"
    assert store.events[-1]["event_type"] == "procedural_skill.failed"


def test_executor_rejects_invalid_orchestrator_completion_receipt():
    executor, _, _, orchestrator, _ = make_executor(
        orchestrator=FakeOrchestrator(invalid_receipt=True)
    )

    result = executor.execute("test.system_audit", run_id="receipt-001")

    assert result["status"] == "failed"
    assert result["reason"].endswith("invalid_step_completion_receipt")
    assert len(orchestrator.calls) == 1


def test_executor_enforces_step_budget_before_dispatch():
    executor, _, _, orchestrator, _ = make_executor(
        capability_seconds=9,
        capability_ram=16,
    )

    result = executor.execute("test.system_audit", run_id="budget-001")

    assert result["status"] == "blocked"
    assert result["reason"] == "step_exceeds_skill_budget:hardware"
    assert orchestrator.calls == []


def test_executor_rejects_background_mode_until_per_step_platform_scheduling_exists():
    executor, _, _, orchestrator, _ = make_executor()

    with pytest.raises(ProceduralSkillExecutionError, match="somente foreground"):
        executor.execute(
            "test.system_audit",
            run_id="background-001",
            work_mode="background_companion",
        )

    assert orchestrator.calls == []


def test_governed_adapter_persists_compact_checkpoint_without_embedding_result():
    checkpoints = []

    class Context:
        def check(self):
            return None

        def checkpoint(self, state):
            checkpoints.append(state)
            return {"sequence": len(checkpoints)}

    binding = ReadOnlyCapabilityAdapters._governed_binding(
        "hardware.snapshot",
        lambda: {"temperature_c": 36.0, "status": "available"},
    )
    result = binding(execution_context=Context())

    assert result == {"temperature_c": 36.0, "status": "available"}
    assert len(checkpoints) == 1
    assert checkpoints[0]["completed"] is True
    assert checkpoints[0]["capability_id"] == "hardware.snapshot"
    assert "temperature_c" not in checkpoints[0]
    assert len(checkpoints[0]["result_sha256"]) == 64


def _capability(capability_id, *, enabled=False):
    return {
        "id": capability_id,
        "name": capability_id,
        "purpose": "Read-only adapter fixture.",
        "description": "Read-only adapter fixture.",
        "version": "1.0.0",
        "risk": "read_only",
        "maturity_state": "implemented",
        "source_module": "tests",
        "operations": ["fixture.operation"],
        "inputs": {},
        "outputs": {},
        "dependencies": [],
        "tools": [],
        "limitations": [],
        "resource_requirements": {
            "estimated_runtime_seconds": 2,
            "estimated_ram_mb": 32,
        },
        "validation": {},
        "enabled": enabled,
        "metadata": {},
    }


def test_register_enabled_adapters_uses_manifest_catalog_and_shared_orchestrator(tmp_path):
    capability_ids = ReadOnlyCapabilityAdapters.CAPABILITY_IDS
    manifest_path = tmp_path / "config" / "capability_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({
        "schema": "mahoraga.capability_manifest",
        "version": "1.0.0",
        "capabilities": [
            _capability(item, enabled=(item == "hardware.snapshot"))
            for item in capability_ids
        ],
    }), encoding="utf-8")
    manifest = CapabilityManifest(manifest_path)
    store = KnowledgeStore(tmp_path / "procedural-adapters.sqlite3")
    dharma = Dharma(tmp_path)
    cognitive = SimpleNamespace(store=store, dharma=dharma)
    orchestrator = ResearchOrchestrator(
        cognitive,
        capability_manifest=manifest,
    )

    hardware = SimpleNamespace(snapshot=lambda: {"status": "available"})
    tools = SimpleNamespace()
    knowledge = SimpleNamespace(store=store)
    introspection = SimpleNamespace(
        store=store,
        hardware=hardware,
        tools=tools,
    )
    core = SimpleNamespace(
        store=store,
        hardware=hardware,
        tools=tools,
        knowledge=knowledge,
        cognitive=cognitive,
        introspection=introspection,
        research_orchestrator=orchestrator,
    )
    adapters = ReadOnlyCapabilityAdapters(core)

    result = adapters.register_enabled()

    assert result["status"] == "registered"
    assert result["registered"] == ["hardware.snapshot"]
    descriptor = orchestrator.capability_descriptor("hardware.snapshot")
    assert descriptor["risk"] == "read_only"
    assert descriptor["checkpointable"] is True
    assert descriptor["estimated_runtime_seconds"] == 2
    assert descriptor["estimated_ram_mb"] == 32
    assert orchestrator.capability_descriptor("memory.history_read") is None
    assert store.list_capabilities()



def test_executor_defers_after_a_step_when_total_runtime_budget_is_exhausted(monkeypatch):
    executor, _, _, orchestrator, store = make_executor()
    clock = iter([100.0, 100.0, 109.0])
    monkeypatch.setattr("agent.procedural_skill_executor.time.monotonic", lambda: next(clock))

    result = executor.execute("test.system_audit", run_id="deadline-001")

    assert result["status"] == "deferred"
    assert result["completed_steps"] == ["hardware"]
    assert result["reason"] == "skill_runtime_budget_exhausted_after_step"
    assert len(orchestrator.calls) == 1
    assert store.events[-1]["event_type"] == "procedural_skill.deferred"



class GovernedFakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "procedural-test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }

    def runtime_context(self):
        return {
            "app_foreground": True,
            "screen_interactive": True,
            "thermal_status": "normal",
            "source": "procedural_test_fixture",
        }

    def battery(self):
        return {"termux_api": {"data": {"percentage": 90, "status": "charging"}}}

    def memory(self):
        return {"values": {"MemAvailable": {"mb": 4096}}}

    def storage(self):
        return {"project": {"free_bytes": 8 * 1024 * 1024 * 1024}}

    def thermal(self):
        return {"status": "normal"}


def test_system_audit_executes_end_to_end_through_real_integrated_core(tmp_path):
    source_root = Path(__file__).resolve().parents[1]
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("capability_manifest.json", "procedural_skills.json"):
        (config_dir / name).write_text(
            (source_root / "config" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    manifest_path = config_dir / "capability_manifest.json"
    manifest_document = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_capabilities = {
        "hardware.snapshot",
        "introspection.capability_audit",
        "memory.history_read",
    }
    for definition in manifest_document["capabilities"]:
        if definition["id"] in required_capabilities:
            definition["enabled"] = True
    manifest_path.write_text(
        json.dumps(manifest_document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    skills_path = config_dir / "procedural_skills.json"
    skills_document = json.loads(skills_path.read_text(encoding="utf-8"))
    skill = next(
        item for item in skills_document["skills"]
        if item["id"] == "mahoraga.system_audit"
    )
    skill["enabled"] = True
    skill["maturity_state"] = "operational"
    skill["evidence"] = ["fixture://system-audit-validation"]
    skills_path.write_text(
        json.dumps(skills_document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    core = IntegratedCore(
        root=tmp_path,
        store=KnowledgeStore(tmp_path / "procedural-e2e.sqlite3"),
        hardware=GovernedFakeHardware(),
    )
    core.procedural_skills.evidence_verifier = SimpleNamespace(
        verify_local=lambda reference: {
            "valid": True,
            "reference": reference,
            "source": "isolated-test-fixture",
        }
    )

    result = core.execute_procedural_skill(
        "mahoraga.system_audit",
        run_id="system-audit-e2e-001",
    )

    assert result["status"] == "completed"
    assert result["execution_performed"] is True
    assert result["tool_dispatch_performed"] is False
    report = result["output"]["report"]
    assert report["completed_steps"] == [
        "hardware",
        "capability_audit",
        "memory_history",
    ]
    assert report["artifact_materialization"] == "not_performed"
    assert len(report["step_results"]) == 3
    assert core.research_orchestrator.status()["runtime_bound_count"] == 3
    assert core.store.count_events("procedural_skill.completed") == 1
    assert core.store.count_events("orchestrator.task.checkpoint") == 3
