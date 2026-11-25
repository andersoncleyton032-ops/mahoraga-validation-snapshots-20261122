from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.store import KnowledgeStore
from agent.visual_document_store import VisualDocumentStore
from scripts.visual_document_lab import VisualDocumentLab


class HeadlessCore:
    def __init__(self, database: Path):
        self.store = KnowledgeStore(database)
        self.visual_documents = VisualDocumentStore(self.store)
        self.image_task_executor = SimpleNamespace(
            execute=lambda *args, **kwargs: pytest.fail("executor should remain gated")
        )

    def inspect_visual_backend_selection(self, task_spec):
        return {
            "status": "blocked",
            "reason": "headless_test_selector_blocks",
            "execution_performed": False,
        }

    def execute_image_task(self, *args, **kwargs):
        return self.image_task_executor.execute(*args, **kwargs)


def make_lab(tmp_path: Path) -> tuple[VisualDocumentLab, HeadlessCore]:
    core = HeadlessCore(tmp_path / "memory.sqlite3")
    return VisualDocumentLab(core), core


def test_visual_lab_creates_three_immutable_revisions_and_compiles(tmp_path):
    lab, core = make_lab(tmp_path)

    created = lab.create_demo("lab.test.scene")
    report = lab.run("lab.test.scene", task_id="task.lab.test")

    assert created["revision"] == 3
    assert len(core.visual_documents.list_revisions("lab.test.scene")) == 3
    assert report["compile"]["status"] == "ready_for_governed_executor"
    assert report["compile"]["execution_started"] is False
    assert report["compile"]["source_document_sha256"] == created["sha256"]
    assert report["compile"]["render_provenance"]["source_provenance_authenticated"] is False


def test_visual_lab_edit_appends_revision_and_preserves_parent_hash(tmp_path):
    lab, core = make_lab(tmp_path)
    lab.create_demo("lab.test.edit")

    edited = lab.edit_transform(
        "lab.test.edit", "element.sphere", (1.0, 2.0, 3.0),
    )
    loaded = core.visual_documents.get("lab.test.edit")

    assert edited["revision"] == 4
    assert loaded is not None
    assert loaded.parent_sha256 is not None
    sphere = next(item for item in loaded.document.elements if item.element_id == "element.sphere")
    assert sphere.transform.translation == (1.0, 2.0, 3.0)


def test_visual_lab_never_calls_executor_when_manifest_gate_blocks(tmp_path, monkeypatch):
    lab, core = make_lab(tmp_path)

    def forbidden_execute(*args, **kwargs):
        pytest.fail("executor must not be called when selector blocks")

    monkeypatch.setattr(core.image_task_executor, "execute", forbidden_execute)
    lab.create_demo("lab.test.blocked")
    report = lab.run("lab.test.blocked", task_id="task.lab.blocked", execute=True)

    assert report["backend_selection"]["status"] == "blocked"
    assert report["execution"]["status"] == "backend_not_governed"
    assert report["execution"]["execution_performed"] is False
    assert report["capability_activation_performed"] is False
