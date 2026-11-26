from pathlib import Path

import pytest

from agent.blender_bridge import ALLOWED_TASKS
from agent.blender_intelligence import BlenderIntelligence


ROOT = Path(__file__).resolve().parents[1]


class FakeBridge:
    def __init__(self):
        self.calls = []

    def submit_task(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return 1


def test_remote_blender_bridge_is_read_only_by_default():
    assert ALLOWED_TASKS == {"scene.inspect"}


@pytest.mark.parametrize(
    "task_type",
    [
        "scene.create",
        "mesh.primitive",
        "object.transform",
        "material.create",
        "light.create",
        "camera.configure",
        "render",
        "project.save",
        "mahoraga.generate",
        "python.execute",
    ],
)
def test_mutating_or_executable_task_types_are_not_queueable(task_type):
    assert task_type not in ALLOWED_TASKS


def test_boolean_approval_cannot_enable_blender_python_execution():
    bridge = FakeBridge()
    intelligence = BlenderIntelligence(bridge=bridge)

    with pytest.raises(PermissionError, match="atestado verificável"):
        intelligence.request_python_execution(
            "bpy.ops.mesh.primitive_cube_add()",
            human_approved=True,
        )

    assert bridge.calls == []


def test_blender_server_binds_loopback_only():
    source = (ROOT / "agent" / "blender_server_v2.py").read_text(
        encoding="utf-8"
    )

    assert 'HOST = "127.0.0.1"' in source
    assert 'HOST = "0.0.0.0"' not in source


def test_blender_lab_manual_fixture_scripts_remain_reversible():
    readme = (ROOT / "blender_lab" / "README.md").read_text(encoding="utf-8")

    assert "não salva o arquivo .blend" in readme.lower()
    assert "rollback" in readme.lower()
    assert "scene.inspect" in readme
    assert "Tarefas de criação/transformação" in readme
