import json
from types import SimpleNamespace

import pytest

from agent.capability_manifest import CapabilityManifest
from agent.procedural_skills import ProceduralSkillRegistry


def capability(capability_id, *, enabled=False, risk="read_only"):
    return {
        "id": capability_id,
        "name": capability_id,
        "purpose": "Capability fixture.",
        "description": "Read-only fixture.",
        "version": "1.0.0",
        "risk": risk,
        "maturity_state": "implemented",
        "source_module": "tests",
        "operations": ["fixture.operation"],
        "inputs": {},
        "outputs": {},
        "dependencies": [],
        "tools": [],
        "limitations": [],
        "resource_requirements": {},
        "validation": {},
        "enabled": enabled,
        "metadata": {},
    }


def make_skill(*, enabled=False, maturity="designed", steps=None):
    return {
        "id": "test.system_audit",
        "version": "1.0.0",
        "domain": "internal_systems",
        "description": "Auditoria local controlada.",
        "intent_triggers": ["auditar o sistema", "inspecionar capacidades"],
        "exclusions": ["instalar pacotes", "alterar permissões"],
        "input_schema": {
            "scope": {"type": "string", "required": False, "description": "Área."}
        },
        "output_schema": {
            "report": {"type": "object", "required": True, "description": "Relatório."}
        },
        "preconditions": ["Manifesto válido."],
        "environment": {"runtime": "local_python", "network": False},
        "dependencies": ["agent.integration_core"],
        "tools": [],
        "risk": "read_only",
        "permissions": ["read_local_state"],
        "resource_budget": {
            "max_runtime_seconds": 8,
            "max_ram_mb": 64,
            "max_steps": 2,
        },
        "steps": steps if steps is not None else [
            {
                "id": "hardware",
                "capability_id": "hardware.snapshot",
                "purpose": "Ler hardware.",
                "input_bindings": {},
                "checkpoint_required": True,
            },
            {
                "id": "audit",
                "capability_id": "introspection.capability_audit",
                "purpose": "Auditar capacidades.",
                "input_bindings": {"scope": "input.scope"},
                "checkpoint_required": True,
            },
        ],
        "expected_artifacts": ["audit_report"],
        "validators": ["schema", "capability_binding", "resource_budget", "provenance"],
        "failure_recovery": {
            "retry_policy": "bounded",
            "max_retries": 1,
            "checkpoint_policy": "after_each_step",
            "on_failure": "preserve_partial_and_stop",
        },
        "provenance": {
            "source": "test fixture",
            "license": "internal",
            "version": "1.0.0",
        },
        "rollback": "read_only_no_mutation",
        "evidence": ["ci:test fixture"] if maturity in {"operational", "specialized"} else [],
        "maturity_state": maturity,
        "enabled": enabled,
    }


def make_manifest(tmp_path, *, enabled=False, second_risk="read_only"):
    path = tmp_path / "config" / "capability_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema": "mahoraga.capability_manifest",
        "version": "1.0.0",
        "capabilities": [
            capability("hardware.snapshot", enabled=enabled),
            capability(
                "introspection.capability_audit",
                enabled=enabled,
                risk=second_risk,
            ),
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return CapabilityManifest(path)


def write_skills(tmp_path, skills, *, raw=None):
    path = tmp_path / "config" / "procedural_skills.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        raw if raw is not None else json.dumps({
            "schema": "mahoraga.procedural_skills",
            "version": "1.0.0",
            "skills": skills,
        }),
        encoding="utf-8",
    )
    return path


class FakeOrchestrator:
    def __init__(self, registered=()):
        self.registered = list(registered)
        self.calls = 0

    def status(self):
        self.calls += 1
        return {"registered_capabilities": [{"id": value} for value in self.registered]}


class FakeEvidenceVerifier:
    def verify_local(self, reference):
        return {"valid": True, "reference": reference}


class FakeStore:
    def __init__(self):
        self.events = []

    def list_tools(self):
        return []

    def record_event(self, event_type, payload):
        self.events.append((event_type, payload))
        return len(self.events)


def registry(
    tmp_path, *, skill=None, manifest_enabled=False, orchestrator=None,
    store=None, evidence_verifier=None,
):
    manifest = make_manifest(tmp_path, enabled=manifest_enabled)
    path = write_skills(tmp_path, [skill or make_skill()])
    return ProceduralSkillRegistry(
        path, manifest, orchestrator=orchestrator, store=store,
        evidence_verifier=evidence_verifier,
    )


def test_registry_loads_contract_without_loading_executable_code(tmp_path):
    item = registry(tmp_path)
    assert item.valid
    assert item.status()["declared_count"] == 1
    assert item.status()["code_loading_enabled"] is False
    assert item.status()["execution_enabled"] is False


def test_production_skill_is_declared_but_blocked_by_default():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    manifest = CapabilityManifest(root / "config" / "capability_manifest.json")
    skills = ProceduralSkillRegistry(
        root / "config" / "procedural_skills.json", manifest
    )
    assert skills.valid
    assert skills.status()["declared_count"] == 1
    assert skills.status()["enabled_count"] == 0
    plan = skills.plan("mahoraga.system_audit")
    assert plan["status"] == "blocked"
    assert plan["steps"] == []
    assert plan["execution_performed"] is False


def test_disabled_capability_prevents_skill_readiness(tmp_path):
    item = registry(
        tmp_path,
        skill=make_skill(enabled=True, maturity="operational"),
        orchestrator=FakeOrchestrator([
            "hardware.snapshot", "introspection.capability_audit"
        ]),
    )
    readiness = item.readiness("test.system_audit")
    assert readiness["ready"] is False
    assert "capability_disabled:hardware.snapshot" in readiness["blockers"]


def test_runtime_binding_is_required_even_when_manifest_is_enabled(tmp_path):
    item = registry(
        tmp_path,
        skill=make_skill(enabled=True, maturity="operational"),
        manifest_enabled=True,
        orchestrator=FakeOrchestrator(["hardware.snapshot"]),
    )
    readiness = item.readiness("test.system_audit")
    assert readiness["ready"] is False
    assert "capability_not_runtime_bound:introspection.capability_audit" in readiness["blockers"]


def test_fully_gated_skill_can_produce_plan_but_never_dispatch(tmp_path):
    orchestrator = FakeOrchestrator([
        "hardware.snapshot", "introspection.capability_audit"
    ])
    item = registry(
        tmp_path,
        skill=make_skill(enabled=True, maturity="operational"),
        manifest_enabled=True,
        orchestrator=orchestrator,
        evidence_verifier=FakeEvidenceVerifier(),
    )
    plan = item.plan("test.system_audit", {"scope": "hardware"})
    assert plan["status"] == "planned"
    assert len(plan["steps"]) == 2
    assert plan["dispatch_performed"] is False
    assert plan["execution_performed"] is False
    assert orchestrator.calls > 0


def test_intent_matching_is_deterministic_and_exclusions_win(tmp_path):
    item = registry(tmp_path)
    matched = item.match_intent("Preciso auditar o sistema e inspecionar capacidades")
    assert matched["status"] == "matched"
    assert matched["matches"][0]["skill_id"] == "test.system_audit"
    assert matched["semantic_recruitment"] is False
    excluded = item.match_intent("auditar o sistema e instalar pacotes")
    assert excluded["status"] == "no_match"


def test_unknown_capability_reference_invalidates_package(tmp_path):
    skill = make_skill()
    skill["steps"][0]["capability_id"] = "missing.capability"
    item = registry(tmp_path, skill=skill)
    assert item.valid is False
    assert item.status()["declared_count"] == 0


def test_step_cannot_escalate_skill_risk(tmp_path):
    skill = make_skill()
    manifest = make_manifest(tmp_path, second_risk="local_compute")
    path = write_skills(tmp_path, [skill])
    item = ProceduralSkillRegistry(path, manifest)
    assert item.valid is False
    assert "excede a classe de risco" in item.status()["error"]


def test_executable_content_is_rejected_recursively(tmp_path):
    skill = make_skill()
    skill["environment"]["nested"] = {"python_code": "print('unsafe')"}
    item = registry(tmp_path, skill=skill)
    assert item.valid is False
    assert "environment" in item.status()["error"]


def test_forward_step_reference_is_rejected(tmp_path):
    skill = make_skill()
    skill["steps"][0]["input_bindings"] = {"value": "step.audit.result"}
    item = registry(tmp_path, skill=skill)
    assert item.valid is False
    assert "etapa futura" in item.status()["error"]


def test_unknown_and_missing_inputs_are_rejected(tmp_path):
    item = registry(tmp_path)
    with pytest.raises(ValueError, match="Entradas inválidas"):
        item.plan("test.system_audit", {"not_declared": True})


def test_resource_budget_cannot_exceed_orchestrator_ceiling(tmp_path):
    skill = make_skill()
    skill["resource_budget"]["max_runtime_seconds"] = 21
    item = registry(tmp_path, skill=skill)
    assert item.valid is False
    assert "Orçamento de recursos" in item.status()["error"]


def test_plan_persistence_records_audit_event_without_execution(tmp_path):
    store = FakeStore()
    item = registry(tmp_path, store=store)
    result = item.plan("test.system_audit", persist=True)
    assert result["status"] == "blocked"
    assert result["event_recorded"] is True
    assert store.events[0][0] == "procedural_skill.plan"
    assert store.events[0][1]["execution_performed"] is False


def test_missing_orchestrator_fails_closed(tmp_path):
    item = registry(
        tmp_path,
        skill=make_skill(enabled=True, maturity="operational"),
        manifest_enabled=True,
    )
    readiness = item.readiness("test.system_audit")
    assert readiness["ready"] is False
    assert "orchestrator_unavailable" in readiness["blockers"]


def test_input_values_must_match_declared_types(tmp_path):
    item = registry(tmp_path)
    with pytest.raises(ValueError, match="Tipo inválido"):
        item.plan("test.system_audit", {"scope": 42})


def test_environment_cannot_enable_network_or_device_mutation(tmp_path):
    skill = make_skill()
    skill["environment"]["network"] = True
    item = registry(tmp_path, skill=skill)
    assert item.valid is False
    assert "efeito externo" in item.status()["error"]


def test_boolean_is_not_accepted_as_integer_budget(tmp_path):
    skill = make_skill()
    skill["resource_budget"]["max_steps"] = True
    item = registry(tmp_path, skill=skill)
    assert item.valid is False
    assert "Orçamento de recursos" in item.status()["error"]


def test_operational_maturity_requires_recorded_evidence(tmp_path):
    skill = make_skill(enabled=True, maturity="operational")
    skill["evidence"] = []
    item = registry(tmp_path, skill=skill)
    assert item.valid is False
    assert "exige evidência" in item.status()["error"]


def test_operational_skill_without_trusted_evidence_verifier_is_not_ready(tmp_path):
    item = registry(
        tmp_path,
        skill=make_skill(enabled=True, maturity="operational"),
        manifest_enabled=True,
        orchestrator=FakeOrchestrator([
            "hardware.snapshot", "introspection.capability_audit"
        ]),
    )
    readiness = item.readiness("test.system_audit")
    assert readiness["ready"] is False
    assert "evidence_verifier_unavailable" in readiness["blockers"]


def test_unverified_evidence_reference_blocks_operational_skill(tmp_path):
    class RejectEvidence:
        def verify_local(self, reference):
            return {"valid": False, "reference": reference}

    item = registry(
        tmp_path,
        skill=make_skill(enabled=True, maturity="operational"),
        manifest_enabled=True,
        orchestrator=FakeOrchestrator([
            "hardware.snapshot", "introspection.capability_audit"
        ]),
        evidence_verifier=RejectEvidence(),
    )
    readiness = item.readiness("test.system_audit")
    assert readiness["ready"] is False
    assert "evidence_unverified:ci:test fixture" in readiness["blockers"]
