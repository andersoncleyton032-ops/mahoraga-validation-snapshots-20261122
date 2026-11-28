from types import SimpleNamespace

import pytest

from agent.background_capabilities import InternalBackgroundCapabilities


class FakeManifest:
    valid = True

    def __init__(
        self,
        *,
        enabled=True,
        tools=None,
        binding_type="explicit_trusted_runtime_registration",
        checkpointable=True,
        max_runtime_seconds=8,
        max_ram_mb=64,
    ):
        self.declaration = {
            "enabled": enabled,
            "risk": "local_compute",
            "tools": [] if tools is None else tools,
            "metadata": {
                "binding_type": binding_type,
                "checkpointable": checkpointable,
                "writes_internal_state": True,
                "external_effects_allowed": False,
                "network_access_allowed": False,
                "tool_dispatch_allowed": False,
            },
            "resource_requirements": {
                "max_runtime_seconds": max_runtime_seconds,
                "max_ram_mb": max_ram_mb,
                "checkpointable": True,
            },
        }

    def get(self, capability_id):
        assert capability_id == InternalBackgroundCapabilities.CAPABILITY_ID
        return self.declaration


class FakeOrchestrator:
    def __init__(self, *, manifest=None, sync_status="synced", registration=None):
        self.capability_manifest = manifest or FakeManifest()
        self.sync_status = sync_status
        self.registration = registration
        self.register_calls = []

    def sync_manifest_catalog(self):
        return {"status": self.sync_status, "conflicts": []}

    def capability_descriptor(self, capability_id):
        return None

    def register_capability(self, capability_id, function, **kwargs):
        self.register_calls.append((capability_id, function, kwargs))
        if self.registration is not None:
            return self.registration
        return {"id": capability_id, "registered": True, **kwargs}


class FakeExecutionContext:
    def __init__(self):
        self.check_count = 0
        self.checkpoints = []

    def check(self):
        self.check_count += 1

    def checkpoint(self, payload):
        self.checkpoints.append(payload)


def safe_result(**overrides):
    return {
        "status": "adopted",
        "autonomy_scope": "internal_only",
        "goal_created": True,
        "goal_id": None,
        "goal": {"goal_id": "goal-from-nested-object"},
        "execution_performed": False,
        "tool_dispatch_performed": False,
        "external_effects_allowed": False,
        "network_access_allowed": False,
        "external_effects_performed": False,
        "network_access_performed": False,
        **overrides,
    }


def make_core(*, manifest=None, sync_status="synced", registration=None, result=None):
    orchestrator = FakeOrchestrator(
        manifest=manifest,
        sync_status=sync_status,
        registration=registration,
    )
    executive = SimpleNamespace(
        adopt_next_internal_inquiry=lambda: safe_result() if result is None else result
    )
    perception = SimpleNamespace(
        reconcile_observation_intents=lambda: {
            "status": "reconciled", "examined": 0, "completed": 0, "reopened": 0
        }
    )
    return SimpleNamespace(
        research_orchestrator=orchestrator,
        executive=executive,
        perception=perception,
    ), orchestrator


def test_manifest_preflight_requires_enabled_allowlisted_internal_scope():
    result = InternalBackgroundCapabilities.inspect_manifest(FakeManifest())
    assert result["status"] == "enabled"

    disabled = InternalBackgroundCapabilities.inspect_manifest(
        FakeManifest(enabled=False)
    )
    assert disabled["status"] == "blocked"
    assert disabled["reason"] == "capability_disabled_in_manifest"


@pytest.mark.parametrize(
    "manifest,reason",
    [
        (FakeManifest(tools=["browser"]), "capability_tool_scope_mismatch"),
        (FakeManifest(binding_type="untrusted_runtime"), "capability_registration_contract_mismatch"),
        (FakeManifest(checkpointable=False), "capability_registration_contract_mismatch"),
        (FakeManifest(max_runtime_seconds=9), "capability_resource_contract_mismatch"),
    ],
)
def test_manifest_preflight_rejects_scope_or_budget_expansion(manifest, reason):
    result = InternalBackgroundCapabilities.inspect_manifest(manifest)
    assert result["status"] == "blocked"
    assert result["reason"] == reason


def test_registration_requires_confirmed_manifest_sync_and_exact_registration():
    core, orchestrator = make_core(sync_status="unavailable")
    result = InternalBackgroundCapabilities(core).register()
    assert result["status"] == "blocked"
    assert result["reason"] == "manifest_catalog_sync_not_confirmed"
    assert orchestrator.register_calls == []

    core, orchestrator = make_core(
        registration={
            "id": InternalBackgroundCapabilities.CAPABILITY_ID,
            "registered": False,
        }
    )
    result = InternalBackgroundCapabilities(core).register()
    assert result["status"] == "blocked"
    assert result["reason"] == "capability_registration_not_confirmed"


def test_registration_succeeds_only_after_sync_and_exact_id_confirmation():
    core, orchestrator = make_core()
    result = InternalBackgroundCapabilities(core).register()
    assert result["status"] == "registered"
    assert result["registered"] is True
    assert result["capability_id"] == InternalBackgroundCapabilities.CAPABILITY_ID
    assert len(orchestrator.register_calls) == 1


def test_internal_adoption_extracts_goal_id_and_returns_checkpoint_receipt():
    core, _ = make_core()
    context = FakeExecutionContext()

    result = InternalBackgroundCapabilities(core)._adopt_next_inquiry(context)

    assert result["goal_created"] is True
    assert result["goal_id"] == "goal-from-nested-object"
    assert result["capability_id"] == InternalBackgroundCapabilities.CAPABILITY_ID
    assert result["autonomy_scope"] == "internal_only"
    assert result["external_effects_allowed"] is False
    assert result["network_access_allowed"] is False
    assert result["execution_performed"] is False
    assert result["tool_dispatch_performed"] is False
    assert result["external_effects_performed"] is False
    assert result["network_access_performed"] is False
    assert context.check_count >= 4
    assert len(context.checkpoints) >= 3


@pytest.mark.parametrize(
    "overrides,missing",
    [
        ({"execution_performed": True}, False),
        ({"tool_dispatch_performed": True}, False),
        ({"external_effects_allowed": True}, False),
        ({"network_access_allowed": True}, False),
        ({"external_effects_performed": True}, False),
        ({"network_access_performed": True}, False),
        ({"autonomy_scope": "external"}, False),
        ({}, True),
    ],
)
def test_internal_adoption_fails_closed_on_execution_or_ambiguous_flags(overrides, missing):
    result = safe_result(**overrides)
    if missing:
        result.pop("network_access_allowed")
    core, _ = make_core(result=result)

    with pytest.raises(PermissionError):
        InternalBackgroundCapabilities(core)._adopt_next_inquiry(FakeExecutionContext())


def test_created_goal_without_identifiable_goal_id_is_rejected():
    result = safe_result(goal={"status": "planned"}, goal_id=None)
    core, _ = make_core(result=result)

    with pytest.raises(ValueError, match="goal_id"):
        InternalBackgroundCapabilities(core)._adopt_next_inquiry(FakeExecutionContext())
