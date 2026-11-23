import json
from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore


class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


class GovernedFakeHardware(FakeHardware):
    def runtime_context(self):
        return {
            "app_foreground": True,
            "screen_interactive": True,
            "thermal_status": "normal",
            "source": "test_fixture",
        }

    def battery(self):
        return {
            "termux_api": {
                "data": {"percentage": 90, "status": "charging"},
            },
        }

    def memory(self):
        return {
            "values": {
                "MemAvailable": {"mb": 4096},
            },
        }

    def storage(self):
        return {
            "project": {"free_bytes": 8 * 1024 * 1024 * 1024},
        }

    def thermal(self):
        return {"status": "normal"}


def make_core(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    return IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=FakeHardware(),
    )


def test_integrated_core_shares_existing_components(tmp_path):
    core = make_core(tmp_path)

    assert core.cognitive.store is core.store
    assert core.cognitive.knowledge is core.knowledge
    assert core.cognitive.dharma is core.dharma
    assert core.introspection.store is core.store
    assert core.introspection.hardware is core.hardware
    assert core.introspection.tools is core.tools
    assert core.metacognition is core.cognitive.metacognition
    assert core.metacognition.store is core.store
    assert core.introspection.metacognition is core.metacognition


def test_integrated_report_is_read_only_by_default(tmp_path):
    core = make_core(tmp_path)

    report = core.build_report()

    assert report["schema"] == "mahoraga.integrated_report"
    assert report["status"] == "healthy"
    assert report["integration"]["shared_store"] is True
    assert report["integration"]["shared_dharma"] is True
    assert report["integration"]["discovery_performed"] is False
    assert report["storage"]["integrity"] == "ok"
    assert report["storage"]["counts"]["self_models"] == 0


def test_integrated_report_can_persist_self_model_when_requested(tmp_path):
    core = make_core(tmp_path)

    report = core.build_report(persist=True)

    assert report["identity"]["name"] == "Mahoraga"
    assert core.store.counts()["self_models"] == 1


def test_inconsistent_shared_components_are_rejected(tmp_path):
    from agent.cognitive_engine import CognitiveEngine
    from agent.store import KnowledgeStore

    root = tmp_path / "project"
    root.mkdir()
    primary_store = KnowledgeStore(tmp_path / "primary.sqlite3")
    separate_store = KnowledgeStore(tmp_path / "separate.sqlite3")
    foreign_cognitive = CognitiveEngine(store=separate_store)

    try:
        IntegratedCore(
            root=root,
            store=primary_store,
            hardware=FakeHardware(),
            cognitive=foreign_cognitive,
        )
    except RuntimeError as exc:
        assert "cognitive_store" in str(exc)
    else:
        raise AssertionError("Componentes com bancos diferentes foram aceitos.")

def test_integrated_report_uses_compact_hardware_summary(tmp_path):
    core = make_core(tmp_path)

    report = core.build_report()

    assert report["capabilities"]["runtime_command_count"] == 1
    assert report["capabilities"]["runtime_commands"] == ["python"]
    assert report["hardware"]["android"]["model"] == "test-device"
    assert "details" not in report
    assert report["access_adaptation"]["status"] == "policy_defined_not_yet_executed"


def test_integrated_report_can_include_full_technical_details(tmp_path):
    core = make_core(tmp_path)

    report = core.build_report(include_details=True)

    assert report["details"]["self_model"]["identity"]["name"] == "Mahoraga"
    assert report["details"]["hardware_snapshot"]["available_tools"]["python"] == "/usr/bin/python"
    assert report["capabilities"]["runtime_command_count"] == 1



def test_integrated_core_connects_cognitive_and_introspection(tmp_path):
    core = make_core(tmp_path)

    assert core.cognitive.introspection is core.introspection
    assert core.cognitive.introspection.store is core.store

def test_integrated_report_exposes_empty_persistent_capability_catalog(tmp_path):
    core = make_core(tmp_path)

    report = core.build_report()

    catalog = report["capability_catalog"]
    assert catalog["catalog_count"] == 0
    assert catalog["runtime_bound_count"] == 0
    assert catalog["unbound_catalog_count"] == 0
    assert catalog["entries"] == []
    assert catalog["manifest"]["state"] == "missing"
    assert catalog["manifest"]["valid"] is False
    assert catalog["manifest"]["declared_count"] == 0
    assert catalog["manifest"]["executable_bindings"] == 0
    assert catalog["manifest"]["code_loading_enabled"] is False
    assert report["capabilities"]["runtime_command_count"] == 1
    assert report["integration"]["research_orchestrator"]["catalog_count"] == 0


def test_integrated_report_exposes_persistent_and_runtime_binding_separately(tmp_path):
    manifest_path = tmp_path / "config" / "capability_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({
            "schema": "mahoraga.capability_manifest",
            "version": "1.0.0",
            "capabilities": [{
                "id": "integration.report_test",
                "name": "Teste do relatório",
                "purpose": "Validar o vínculo explícito.",
                "risk": "read_only",
                "maturity_state": "implemented",
                "enabled": True,
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    core = make_core(tmp_path)
    core.research_orchestrator.sync_manifest_catalog()

    core.research_orchestrator.register_capability(
        "integration.report_test",
        lambda: "ok",
        risk="read_only",
        description="Capacidade registrada para validar o relatório.",
    )

    report = core.build_report()
    catalog = report["capability_catalog"]

    assert catalog["catalog_count"] == 1
    assert catalog["runtime_bound_count"] == 1
    assert catalog["unbound_catalog_count"] == 0
    assert catalog["entries"] == [{
        "id": "integration.report_test",
        "name": "Teste do relatório",
        "risk": "read_only",
        "maturity_state": "implemented",
        "enabled": True,
        "runtime_bound": True,
    }]
    assert "function" not in catalog["entries"][0]
    assert "callable" not in catalog["entries"][0]



def test_integrated_core_composes_inert_read_only_adapters(tmp_path):
    core = make_core(tmp_path)

    assert core.read_only_capability_adapters.core is core
    assert core.research_orchestrator._capabilities == {}
    assert core.store.list_capabilities() == []
    assert core.fabric.connectome_snapshot()["node_count"] >= 20


def test_connectome_represents_every_shared_component_invariant(tmp_path):
    core = make_core(tmp_path)

    snapshot = core.inspect_cognitive_fabric()
    assert "image_generation" in snapshot["nodes"]
    assert "mathematics" in snapshot["nodes"]
    mathematics_edge = next(
        item for item in snapshot["verified_structural_edges"]
        if item["relationship_id"] == "cognitive_mathematics"
    )
    assert mathematics_edge["source"] == "cognitive"
    assert mathematics_edge["target"] == "mathematics"
    assert mathematics_edge["verified"] is True
    image_edge = next(
        item for item in snapshot["verified_structural_edges"]
        if item["relationship_id"] == "image_generation_root"
    )
    assert image_edge["source"] == "image_generation"
    assert image_edge["target"] == "integrated_core"
    assert image_edge["verified"] is True


def test_integrated_core_connects_procedural_skills_to_shared_core_and_connectome(tmp_path):
    core = make_core(tmp_path)

    assert core.procedural_skills.store is core.store
    assert core.procedural_skills.capability_manifest is core.capability_manifest
    assert core.procedural_skills.orchestrator is core.research_orchestrator
    assert core.procedural_skills.evidence_verifier is core.cognitive.evidence_verifier

    snapshot = core.inspect_cognitive_fabric()
    assert "procedural_skills" in snapshot["nodes"]
    relationships = {
        item["relationship_id"]: item
        for item in snapshot["verified_structural_edges"]
    }
    for relationship_id in (
        "procedural_skills_store",
        "procedural_skills_manifest",
        "procedural_skills_orchestrator",
        "procedural_skills_evidence_verifier",
    ):
        assert relationships[relationship_id]["verified"] is True
        assert relationships[relationship_id]["source"] == "procedural_skills"


def test_integrated_core_reuses_cognitive_reasoning_instance(tmp_path):
    core = make_core(tmp_path)
    assert core.reasoning is core.cognitive.reasoning
    assert core.reasoning.cognitive is core.cognitive
    assert core.cognitive.status()["reasoning"]["cognitive_connected"] is True


def test_integrated_core_routes_capability_through_real_governor(tmp_path):
    manifest_path = tmp_path / "config" / "capability_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schema": "mahoraga.capability_manifest",
        "version": "1.0.0",
        "capabilities": [{
            "id": "integration.governed",
            "name": "Capacidade governada",
            "purpose": "Validar admissão pelo Governor real.",
            "risk": "local_compute",
            "maturity_state": "implemented",
            "enabled": True,
        }],
    }), encoding="utf-8")
    core = IntegratedCore(
        root=tmp_path,
        store=KnowledgeStore(tmp_path / "governed.sqlite3"),
        hardware=GovernedFakeHardware(),
    )
    core.research_orchestrator.sync_manifest_catalog()
    executed = []

    def bounded_capability(execution_context):
        execution_context.check()
        executed.append(True)
        return "governed"

    core.research_orchestrator.register_capability(
        "integration.governed",
        bounded_capability,
        risk="local_compute",
        description="Execução integrada com Governor real.",
    )
    result = core.research_orchestrator.run_parallel([{
        "id": "integrated-governed",
        "name": "Execução governada",
        "capability": "integration.governed",
    }])

    assert result["status"] == "completed"
    assert result["tasks"][0]["result"] == "governed"
    assert result["resource_session"]["status"] == "bounded"
    assert result["deadline_enforcement"] == "cooperative"
    assert result["memory_enforcement"] == "admission_only"
    assert executed == [True]
    assert len(core.store.list_events(10)) == 3


def test_integrated_core_reuses_shared_perception_and_autonomy_components(tmp_path):
    core = make_core(tmp_path)

    assert core.perception.store is core.store
    assert core.perception.hardware is core.hardware
    assert core.perception.dharma is core.dharma
    assert core.autonomy.hardware is core.hardware
    assert core.autonomy.dharma is core.dharma
    assert core.research_orchestrator.autonomy is core.autonomy
    assert core.research_orchestrator.runtime_context_provider is None

    report = core.build_report()
    assert report["integration"]["orchestrator_autonomy"] is True
    assert report["integration"]["shared_perception_engine"] is True
    assert report["integration"]["shared_autonomy_governor"] is True
    assert report["integration"]["perception"]["continuous_sampling"] is False
    assert report["integration"]["autonomy_policy"]["automatic_dispatch_enabled"] is False

def test_language_calibration_is_predictor_scoped_and_advisory_only(tmp_path):
    core = make_core(tmp_path)
    calls = []
    expected = {
        "decision": "abstain",
        "abstain": True,
        "reasons": ["amostra verificada insuficiente"],
        "execution_authorized": False,
    }

    def assess(confidence, **kwargs):
        calls.append((confidence, kwargs))
        return expected

    core.cognitive.assess_confidence = assess
    language_result = {
        "recognized": False,
        "decision": "abstain",
        "candidate_intent": "inspect_status",
        "confidence_target": "candidate_intent",
        "confidence": 0.82,
        "predictor_id": "language-model-test-v1",
    }
    original_decision = language_result["decision"]

    result = core._assess_language_calibration(
        language_result,
        correlation_id="cycle-test-001",
    )

    assert result["status"] == "assessed"
    assert result["task"] == "language_intent_classification"
    assert result["predictor_id"] == "language-model-test-v1"
    assert result["candidate_intent"] == "inspect_status"
    assert result["confidence_target"] == "candidate_intent"
    assert result["correlation_id"] == "cycle-test-001"
    assert result["assessment"] is expected
    assert result["advisory_only"] is True
    assert result["behavior_changed"] is False
    assert result["execution_authorized"] is False
    assert calls == [(
        0.82,
        {
            "task": "language_intent_classification",
            "predictor_id": "language-model-test-v1",
        },
    )]
    assert language_result["decision"] == original_decision


def test_language_calibration_is_not_assessed_without_predictor_identity(tmp_path):
    core = make_core(tmp_path)
    called = []
    core.cognitive.assess_confidence = lambda *args, **kwargs: called.append(True)

    result = core._assess_language_calibration(
        {
            "decision": "abstain",
            "candidate_intent": "inspect_status",
            "confidence_target": "candidate_intent",
            "confidence": 0.9,
            "predictor_id": None,
        },
        correlation_id="cycle-test-002",
    )

    assert result["status"] == "not_assessable"
    assert result["behavior_changed"] is False
    assert result["execution_authorized"] is False
    assert called == []



def test_language_calibration_rejects_mismatched_prediction_target(tmp_path):
    core = make_core(tmp_path)
    called = []
    core.cognitive.assess_confidence = lambda *args, **kwargs: called.append(True)

    result = core._assess_language_calibration(
        {
            "decision": "defer",
            "intent": "domain_anchor_intent",
            "intent_source": "domain_anchor",
            "candidate_intent": "model_candidate_intent",
            "confidence_target": "intent",
            "confidence": 0.91,
            "predictor_id": "language-model-test-v1",
        },
        correlation_id="cycle-test-003",
    )

    assert result["status"] == "not_assessable"
    assert "confidence_target" in result["missing_fields"]
    assert called == []


def test_prepare_request_preserves_candidate_target_and_cycle_correlation(tmp_path):
    core = make_core(tmp_path)
    calls = []
    core.language.classify = lambda _text: {
        "recognized": False,
        "decision": "defer",
        "intent": "domain_anchor_intent",
        "intent_source": "domain_anchor",
        "candidate_intent": "model_candidate_intent",
        "confidence_target": "candidate_intent",
        "confidence": 0.91,
        "predictor_id": "language-model-test-v1",
        "reason": "future_or_conditional_intention",
    }

    def assess(confidence, **kwargs):
        calls.append((confidence, kwargs))
        return {
            "decision": "abstain",
            "abstain": True,
            "execution_authorized": False,
        }

    core.cognitive.assess_confidence = assess
    result = core.prepare_request(
        "Amanhã analise a cena.",
        include_capability_review=False,
    )

    assessment = result["metacognitive_assessment"]
    assert result["plan"]["status"] == "deferred"
    assert assessment["candidate_intent"] == "model_candidate_intent"
    assert assessment["confidence_target"] == "candidate_intent"
    assert assessment["correlation_id"] == result["cognitive_fabric"]["cycle_id"]
    assert assessment["candidate_intent"] != result["language"]["intent"]
    assert calls == [(
        0.91,
        {
            "task": "language_intent_classification",
            "predictor_id": "language-model-test-v1",
        },
    )]


def test_integrated_core_exposes_cognitive_mathematics_component(tmp_path):
    core = make_core(tmp_path)

    assert core.mathematics is core.cognitive.mathematics
    assert core.mathematics.status()["component"] == "MathematicsEngine"
    assert core.cognitive.evaluate_math("0.1 + 0.2")["value"]["exact"] == "3/10"
    solved = core.cognitive.solve_linear_equation("3*x/2 = 7/2")
    assert solved["solution"]["exact"] == "7/3"
    assert solved["verification"]["equal"] is True
    assert core.fabric.connectome_snapshot()["node_count"] >= 21



def test_integrated_core_connects_procedural_skill_executor_and_reports_limits(tmp_path):
    core = make_core(tmp_path)

    executor = core.procedural_skill_executor
    assert executor.registry is core.procedural_skills
    assert executor.adapters is core.read_only_capability_adapters
    assert executor.orchestrator is core.research_orchestrator
    assert executor.store is core.store

    snapshot = core.inspect_cognitive_fabric()
    assert "procedural_skill_executor" in snapshot["nodes"]
    relationships = {
        item["relationship_id"]: item
        for item in snapshot["verified_structural_edges"]
    }
    for relationship_id in (
        "procedural_executor_registry",
        "procedural_executor_adapters",
        "procedural_executor_orchestrator",
        "procedural_executor_store",
    ):
        assert relationships[relationship_id]["verified"] is True
        assert relationships[relationship_id]["source"] == "procedural_skill_executor"

    report = core.build_report()
    execution = report["procedural_skill_execution"]
    assert execution["execution_path_implemented"] is True
    assert execution["supported_work_mode"] == "foreground"
    assert execution["background_execution_supported"] is False
    assert execution["network_allowed"] is False
    assert execution["workspace_writes_allowed"] is False



def test_production_procedural_skill_remains_blocked_without_enabling_manifest(tmp_path):
    from pathlib import Path
    import shutil

    source_root = Path(__file__).resolve().parents[1]
    config = tmp_path / "config"
    config.mkdir()
    for name in ("capability_manifest.json", "procedural_skills.json"):
        shutil.copyfile(source_root / "config" / name, config / name)

    store = KnowledgeStore(tmp_path / "production-default.sqlite3")
    core = IntegratedCore(
        root=tmp_path,
        store=store,
        hardware=FakeHardware(),
    )

    result = core.execute_procedural_skill(
        "mahoraga.system_audit",
        run_id="production-disabled-001",
    )

    assert core.capability_manifest.status()["enabled_count"] == 0
    assert core.procedural_skills.status()["enabled_count"] == 0
    assert result["status"] == "blocked"
    assert result["execution_performed"] is False
    assert store.list_capabilities() == []
    assert store.count_events("procedural_skill.blocked") == 1
