from types import SimpleNamespace

import pytest

from agent.background_capabilities import InternalBackgroundCapabilities


class FakeOrchestrator:
    def __init__(self):
        self.registered = []

    def capability_descriptor(self, capability_id):
        return None

    def register_capability(self, capability_id, function, **kwargs):
        self.registered.append((capability_id, function, kwargs))
        return {"status": "registered", "capability_id": capability_id, **kwargs}


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
        research_orchestrator=FakeOrchestrator(),
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {
            "status": "adopted", "goal_created": True, "goal_id": "goal-1",
            "execution_performed": False, "tool_dispatch_performed": False,
        }),
    )
    capability = InternalBackgroundCapabilities(core)
    result = capability.register()

    assert result["status"] == "registered"
    capability_id, function, metadata = core.research_orchestrator.registered[0]
    assert capability_id == "internal.adopt_next_inquiry"
    assert metadata["risk"] == "local_compute"
    assert metadata["checkpointable"] is True
    assert metadata["estimated_runtime_seconds"] == 8
    assert metadata["estimated_ram_mb"] == 64

    context = FakeExecutionContext()
    outcome = function(context)
    assert outcome["goal_created"] is True
    assert outcome["goal_id"] == "goal-1"
    assert outcome["tool_dispatch_performed"] is False
    assert context.checks == 2
    assert len(context.checkpoints) == 2


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


def test_requires_checkpointable_execution_context():
    core = SimpleNamespace(
        research_orchestrator=FakeOrchestrator(),
        executive=SimpleNamespace(adopt_next_internal_inquiry=lambda: {}),
    )
    function = InternalBackgroundCapabilities(core)._adopt_next_inquiry

    with pytest.raises(TypeError):
        function(object())
