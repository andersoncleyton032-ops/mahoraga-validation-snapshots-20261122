import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.background_capabilities import InternalBackgroundCapabilities
from agent.background_work_queue import PersistentBackgroundWorkQueue
from agent.capability_manifest import CapabilityManifest
from agent.dharma import Dharma
from agent.research_orchestrator import ResearchOrchestrator
from agent.store import KnowledgeStore


class FakeManifest:
    valid = True

    def __init__(
        self, *, enabled=True, risk="local_compute", resources=None,
        writes_internal_state=True, external_effects_allowed=False,
        network_access_allowed=False, tool_dispatch_allowed=False,
    ):
        self.enabled = enabled
        self.risk = risk
        self.writes_internal_state = writes_internal_state
        self.external_effects_allowed = external_effects_allowed
        self.network_access_allowed = network_access_allowed
        self.tool_dispatch_allowed = tool_dispatch_allowed
        self.resources = resources or {
            "max_runtime_seconds": 8,
            "max_ram_mb": 64,
            "checkpointable": True,
        }

    def get(self, capability_id):
        if capability_id != "internal.adopt_next_inquiry":
            return None
        return {
            "id": capability_id,
            "enabled": self.enabled,
            "risk": self.risk,
            "resource_requirements": self.resources,
            "metadata": {
                "writes_internal_state": self.writes_internal_state,
                "external_effects_allowed": self.external_effects_allowed,
                "network_access_allowed": self.network_access_allowed,
                "tool_dispatch_allowed": self.tool_dispatch_allowed,
            },
        }


class FakeOrchestrator:
    def __init__(
        self, *, enabled=True, risk="local_compute", manifest=True,
        resources=None, sync_conflict=False, writes_internal_state=True,
        external_effects_allowed=False, network_access_allowed=False,
        tool_dispatch_allowed=False,
    ):
        self.registered = []
        self.capability_manifest = (
            FakeManifest(
                enabled=enabled, risk=risk, resources=resources,
                writes_internal_state=writes_internal_state,
                external_effects_allowed=external_effects_allowed,
                network_access_allowed=network_access_allowed,
                tool_dispatch_allowed=tool_dispatch_allowed,
            )
            if manifest else None
        )
        self.sync_calls = 0
        self.sync_conflict = sync_conflict

    def sync_manifest_catalog(self):
        self.sync_calls += 1
        conflicts = (
            [{"id": "internal.adopt_next_inquiry", "fields": ["enabled"]}]
            if self.sync_conflict else []
        )
        return {"inserted_count": 1, "conflicts": conflicts}

    def capability_descriptor(self, capability_id):
        return None

    def register_capability(self, capability_id, function, **kwargs):
        self.registered.append((capability_id, function, kwargs))
        return {"status": "registered", "capability_id": capability_id, **kwargs}

    def run_parallel(self, tasks, **kwargs):
        raise AssertionError("Worker bloqueado não pode executar tarefas.")


class FakeExecutionContext:
    def __init__(self):
        self.checks = 0
        self.checkpoints = []

    def check(self):
        self.checks += 1

    def checkpoint(self, payload):
        self.checkpoints.append(payload)


def test_registers_only_checkpointable_local_internal_capability():
    core = SimpleNamespace(
        research_orchestrator=FakeOrchestrator(enabled=True),
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {
            "status": "adopted", "goal_created": True, "goal_id": "goal-1",
            "execution_performed": False, "tool_dispatch_performed": False,
        }),
    )
    capability = InternalBackgroundCapabilities(core)
    result = capability.register()

    assert result["status"] == "registered"
    assert result["registered"] is True
    assert core.research_orchestrator.sync_calls == 1
    capability_id, function, metadata = core.research_orchestrator.registered[0]
    assert capability_id == "internal.adopt_next_inquiry"
    assert metadata["risk"] == "local_compute"
    assert metadata["checkpointable"] is True
    assert metadata["writes_internal_state"] is True
    assert metadata["external_effects_allowed"] is False
    assert metadata["network_access_allowed"] is False
    assert metadata["tool_dispatch_allowed"] is False
    assert metadata["estimated_runtime_seconds"] == 8
    assert metadata["estimated_ram_mb"] == 64

    context = FakeExecutionContext()
    outcome = function(context)
    assert outcome["goal_created"] is True
    assert outcome["goal_id"] == "goal-1"
    assert outcome["tool_dispatch_performed"] is False
    assert outcome["external_effects_performed"] is False
    assert outcome["network_access_performed"] is False
    assert context.checks == 4
    assert len(context.checkpoints) == 4


def test_rejects_internal_capability_if_it_dispatches_tools():
    core = SimpleNamespace(
        research_orchestrator=FakeOrchestrator(),
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {
            "status": "invalid", "goal_created": False,
            "tool_dispatch_performed": True,
        }),
    )
    function = InternalBackgroundCapabilities(core)._adopt_next_inquiry

    with pytest.raises(PermissionError):
        function(FakeExecutionContext())


@pytest.mark.parametrize(
    "flag",
    [
        "external_effects_allowed",
        "network_access_allowed",
        "tool_dispatch_allowed",
    ],
)
def test_registration_fails_closed_when_manifest_allows_side_effects(flag):
    orchestrator = FakeOrchestrator(**{flag: True})
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
    )

    result = InternalBackgroundCapabilities(core).register()

    assert result["status"] == "blocked"
    assert result["reason"] == "capability_side_effect_contract_mismatch"
    assert orchestrator.registered == []
    assert orchestrator.sync_calls == 0


@pytest.mark.parametrize(
    "side_effect",
    ["external_effects_performed", "network_access_performed"],
)
def test_handler_rejects_external_or_network_side_effects(side_effect):
    result = {
        "status": "invalid",
        "goal_created": False,
        "tool_dispatch_performed": False,
        side_effect: True,
    }
    core = SimpleNamespace(
        research_orchestrator=FakeOrchestrator(),
        executive=SimpleNamespace(
            adopt_next_internal_inquiry=lambda: result,
        ),
    )
    function = InternalBackgroundCapabilities(core)._adopt_next_inquiry

    with pytest.raises(PermissionError):
        function(FakeExecutionContext())


def test_requires_checkpointable_execution_context():
    core = SimpleNamespace(
        research_orchestrator=FakeOrchestrator(),
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {}),
    )
    function = InternalBackgroundCapabilities(core)._adopt_next_inquiry

    with pytest.raises(TypeError):
        function(object())


def test_registration_fails_closed_when_manifest_capability_is_disabled():
    orchestrator = FakeOrchestrator(enabled=False)
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
    )

    result = InternalBackgroundCapabilities(core).register()

    assert result["status"] == "blocked"
    assert result["registered"] is False
    assert result["reason"] == "capability_disabled_in_manifest"
    assert orchestrator.registered == []
    assert orchestrator.sync_calls == 0


def test_registration_fails_closed_when_manifest_is_missing():
    orchestrator = FakeOrchestrator(manifest=False)
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
    )

    result = InternalBackgroundCapabilities(core).register()

    assert result["status"] == "blocked"
    assert result["registered"] is False
    assert result["reason"] == "capability_manifest_unavailable_or_invalid"
    assert orchestrator.registered == []


def test_registration_fails_closed_on_manifest_risk_mismatch():
    orchestrator = FakeOrchestrator(enabled=True, risk="read_only")
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
    )

    result = InternalBackgroundCapabilities(core).register()

    assert result["status"] == "blocked"
    assert result["reason"] == "capability_risk_mismatch"
    assert orchestrator.registered == []
    assert orchestrator.sync_calls == 0


def test_worker_defers_without_queueing_when_internal_capability_is_disabled(tmp_path):
    from scripts.mahoraga_background_worker import run_worker_once

    store = KnowledgeStore(tmp_path / "worker-disabled.sqlite3")
    orchestrator = FakeOrchestrator(enabled=False)
    core = SimpleNamespace(
        store=store,
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
        hardware=SimpleNamespace(
            runtime_context=lambda: (_ for _ in ()).throw(
                AssertionError("Contexto não deve ser consultado quando bloqueado.")
            )
        ),
    )

    class Wake:
        def schedule_next(self, *, delay_seconds):
            return True

    result = run_worker_once(
        core=core,
        worker_id="worker-disabled-test",
        wake_adapter=Wake(),
    )

    assert result["status"] == "deferred"
    assert result["task_id"] == "capability-gate:internal.adopt_next_inquiry"
    assert result["execution_performed"] is False
    assert result["completion_receipt_valid"] is False
    assert result["wake_schedule"]["status"] == "not_needed"
    assert result["queue"]["active_items"] == 0
    assert orchestrator.registered == []


def test_production_manifest_declares_internal_background_capability_disabled():
    root = Path(__file__).resolve().parents[1]
    manifest = CapabilityManifest(root / "config" / "capability_manifest.json")

    assert manifest.valid is True, manifest.status()
    capability = manifest.get("internal.adopt_next_inquiry")
    assert capability is not None
    assert capability["enabled"] is False
    assert capability["risk"] == "local_compute"
    assert capability["metadata"]["writes_internal_state"] is True
    assert capability["metadata"]["external_effects_allowed"] is False
    assert capability["metadata"]["network_access_allowed"] is False
    assert capability["metadata"]["tool_dispatch_allowed"] is False
    assert manifest.status()["declared_count"] == 17
    assert manifest.status()["enabled_count"] == 0


def test_worker_preserves_pending_queue_and_schedules_retry_when_capability_disabled(tmp_path):
    from scripts.mahoraga_background_worker import run_worker_once

    store = KnowledgeStore(tmp_path / "worker-pending.sqlite3")
    queue = PersistentBackgroundWorkQueue(store)
    queue.enqueue({
        "task_id": "pending-internal",
        "name": "internal inquiry",
        "capability": "internal.adopt_next_inquiry",
        "args": [],
        "kwargs": {},
        "risk": "local_compute",
        "estimated_runtime_seconds": 8,
        "estimated_ram_mb": 64,
        "checkpointable": True,
        "writes_internal_state": True,
    })
    orchestrator = FakeOrchestrator(enabled=False)
    core = SimpleNamespace(
        store=store,
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
        hardware=SimpleNamespace(),
    )

    class Wake:
        def __init__(self):
            self.delays = []

        def schedule_next(self, *, delay_seconds):
            self.delays.append(delay_seconds)
            return True

    wake = Wake()
    result = run_worker_once(
        core=core,
        worker_id="worker-disabled-pending",
        wake_adapter=wake,
    )

    assert result["status"] == "deferred"
    assert result["wake_schedule"]["status"] == "scheduled"
    assert result["queue"]["queued"] == 1
    assert result["queue"]["pending"] is True
    assert wake.delays == [900]
    assert queue.list_items()[0]["task_id"] == "pending-internal"


def test_registration_blocks_manifest_resource_contract_mismatch():
    orchestrator = FakeOrchestrator(
        enabled=True,
        resources={
            "max_runtime_seconds": 9,
            "max_ram_mb": 64,
            "checkpointable": True,
        },
    )
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
    )

    result = InternalBackgroundCapabilities(core).register()

    assert result["status"] == "blocked"
    assert result["reason"] == "capability_resource_contract_mismatch"
    assert orchestrator.registered == []
    assert orchestrator.sync_calls == 0


def test_registration_blocks_persistent_manifest_catalog_conflict():
    orchestrator = FakeOrchestrator(enabled=True, sync_conflict=True)
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
    )

    result = InternalBackgroundCapabilities(core).register()

    assert result["status"] == "blocked"
    assert result["reason"] == "manifest_catalog_conflict"
    assert orchestrator.registered == []
    assert orchestrator.sync_calls == 1


def test_registration_with_real_manifest_and_orchestrator_is_explicit_and_bounded(tmp_path):
    manifest_path = tmp_path / "config" / "capability_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schema": "mahoraga.capability_manifest",
        "version": "1.0.0",
        "capabilities": [{
            "id": "internal.adopt_next_inquiry",
            "name": "Adotar consulta interna",
            "purpose": "Adotar no máximo uma consulta interna.",
            "risk": "local_compute",
            "maturity_state": "implemented",
            "resource_requirements": {
                "max_runtime_seconds": 8,
                "max_ram_mb": 64,
                "checkpointable": True,
            },
            "metadata": {"writes_internal_state": True},
            "enabled": True,
        }],
    }), encoding="utf-8")
    manifest = CapabilityManifest(manifest_path)
    store = KnowledgeStore(tmp_path / "real-registration.sqlite3")
    cognitive = SimpleNamespace(store=store, dharma=Dharma(tmp_path))
    orchestrator = ResearchOrchestrator(
        cognitive,
        capability_manifest=manifest,
    )
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {
            "status": "idle",
            "goal_created": False,
            "tool_dispatch_performed": False,
        }),
    )

    result = InternalBackgroundCapabilities(core).register()
    descriptor = orchestrator.capability_descriptor(
        "internal.adopt_next_inquiry"
    )

    assert result["status"] == "registered"
    assert result["registered"] is True
    assert descriptor["risk"] == "local_compute"
    assert descriptor["estimated_runtime_seconds"] == 8
    assert descriptor["estimated_ram_mb"] == 64
    assert descriptor["checkpointable"] is True
    assert descriptor["writes_internal_state"] is True
    assert orchestrator.status()["runtime_bound_count"] == 1



def test_registration_blocks_capability_without_declared_internal_write_scope():
    orchestrator = FakeOrchestrator(writes_internal_state=False)
    core = SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
    )

    result = InternalBackgroundCapabilities(core).register()

    assert result["status"] == "blocked"
    assert result["registered"] is False
    assert result["reason"] == "capability_internal_write_scope_mismatch"
    assert orchestrator.registered == []
    assert orchestrator.sync_calls == 0



def test_worker_poll_descriptor_declares_internal_state_write():
    from scripts.mahoraga_background_worker import build_poll_task_descriptor

    task = build_poll_task_descriptor(1_800_000_000)

    assert task["capability"] == InternalBackgroundCapabilities.CAPABILITY_ID
    assert task["risk"] == "local_compute"
    assert task["checkpointable"] is True
    assert task["writes_internal_state"] is True



def test_internal_background_cycle_reconciles_perception_before_adopting_inquiry():
    reconciliation = {
        "status": "available",
        "examined": 2,
        "completed": 1,
        "reopened": 1,
        "pending": 0,
        "ambiguous": 0,
        "reconciliation_errors": 0,
    }
    core = SimpleNamespace(
        perception=SimpleNamespace(
            reconcile_observation_intents=lambda: dict(reconciliation)
        ),
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {
            "status": "adopted",
            "goal_created": True,
            "goal_id": "goal-2",
            "execution_performed": False,
            "tool_dispatch_performed": False,
        }),
    )

    result = InternalBackgroundCapabilities(core)._adopt_next_inquiry(
        FakeExecutionContext()
    )

    assert result["perception_reconciliation"] == reconciliation
    assert result["goal_created"] is True
    assert result["goal_id"] == "goal-2"


def test_internal_background_cycle_fails_closed_on_invalid_perception_reconciliation():
    core = SimpleNamespace(
        perception=SimpleNamespace(
            reconcile_observation_intents=lambda: None
        ),
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {
            "status": "adopted",
            "goal_created": True,
            "tool_dispatch_performed": False,
        }),
    )

    with pytest.raises(TypeError, match="reconciliação perceptiva"):
        InternalBackgroundCapabilities(core)._adopt_next_inquiry(
            FakeExecutionContext()
        )


def test_injected_worker_runtime_does_not_import_android_or_integrated_core(
    tmp_path, monkeypatch,
):
    import sys

    from scripts.mahoraga_background_worker import run_worker_once

    store = KnowledgeStore(tmp_path / "injected-worker.sqlite3")
    orchestrator = FakeOrchestrator(enabled=False)
    core = SimpleNamespace(
        store=store,
        research_orchestrator=orchestrator,
        executive=SimpleNamespace(),
        hardware=SimpleNamespace(),
    )

    class Wake:
        def schedule_next(self, *, delay_seconds):
            return True

    # An injected core and wake adapter must make the heavyweight production
    # runtime modules unnecessary for this deterministic worker invocation.
    monkeypatch.setitem(sys.modules, "agent.integration_core", None)
    monkeypatch.setitem(sys.modules, "agent.android_workmanager_wake", None)

    result = run_worker_once(
        core=core,
        now_epoch=1_795_000_000,
        worker_id="worker-injected-test",
        wake_adapter=Wake(),
    )

    assert result["status"] == "deferred"
    assert result["execution_performed"] is False
    assert result["completion_receipt_valid"] is False
    assert result["queue"]["active_items"] == 0
    assert orchestrator.registered == []
