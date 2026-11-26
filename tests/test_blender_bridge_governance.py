from pathlib import Path

import pytest

from agent.blender_bridge import ALLOWED_TASKS, BlenderTaskQueue
from agent.dharma import Dharma
from agent.store import KnowledgeStore, utc_now
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

    assert "salva o arquivo .blend" in readme.lower()
    assert "rollback" in readme.lower()
    assert "scene.inspect" in readme
    assert "Tarefas de criação/transformação" in readme

def test_claim_next_fails_legacy_mutating_tasks_before_read_only_inspection(tmp_path):
    store = KnowledgeStore(tmp_path / "blender.sqlite3")
    queue = BlenderTaskQueue(store, Dharma(tmp_path))
    now = utc_now()

    with store._transaction() as db:
        db.execute(
            """
            INSERT INTO blender_tasks (
                task_type, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            ("mahoraga.generate", "{}", now, now),
        )
        db.execute(
            """
            INSERT INTO blender_tasks (
                task_type, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            ("scene.inspect", "{}", now, now),
        )

    task = queue.claim_next("blender-worker")

    assert task is not None
    assert task["task_type"] == "scene.inspect"
    rows = {row["task_type"]: row for row in queue.list_tasks(limit=10)}
    assert rows["mahoraga.generate"]["status"] == "failed"
    assert rows["mahoraga.generate"]["error"].startswith(
        "blocked_by_current_policy:"
    )
    assert rows["scene.inspect"]["status"] == "claimed"


def test_claim_next_fails_malformed_legacy_payload(tmp_path):
    store = KnowledgeStore(tmp_path / "blender.sqlite3")
    queue = BlenderTaskQueue(store, Dharma(tmp_path))
    now = utc_now()

    with store._transaction() as db:
        db.execute(
            """
            INSERT INTO blender_tasks (
                task_type, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            ("scene.inspect", "{not-json", now, now),
        )

    assert queue.claim_next("blender-worker") is None
    row = queue.list_tasks(limit=1)[0]
    assert row["status"] == "failed"
    assert row["payload"] == {"_decode_error": "invalid_json"}
    assert row["error"].startswith("blocked_by_current_policy:")

