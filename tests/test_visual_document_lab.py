from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

from agent.store import KnowledgeStore
from agent.visual_document_store import VisualDocumentConflictError, VisualDocumentStore
from scripts.visual_document_lab import VisualDocumentLab, main as visual_lab_main


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


def test_visual_lab_creates_complete_document_atomically_and_compiles(tmp_path):
    lab, core = make_lab(tmp_path)

    created = lab.create_demo("lab.test.scene")
    report = lab.run("lab.test.scene", task_id="task.lab.test")

    assert created["revision"] == 1
    assert created["element_count"] == 2
    assert len(core.visual_documents.list_revisions("lab.test.scene")) == 1
    assert report["compile"]["status"] == "ready_for_governed_executor"
    assert report["compile"]["execution_started"] is False
    assert report["compile"]["source_document_sha256"] == created["sha256"]
    assert report["compile"]["render_provenance"]["source_provenance_authenticated"] is False
    with pytest.raises(ValueError, match="não será sobrescrito"):
        lab.create_demo("lab.test.scene")
    assert len(core.visual_documents.list_revisions("lab.test.scene")) == 1


def test_visual_lab_edit_appends_revision_and_preserves_parent_hash(tmp_path):
    lab, core = make_lab(tmp_path)
    lab.create_demo("lab.test.edit")

    edited = lab.edit_transform(
        "lab.test.edit", "element.sphere", (1.0, 2.0, 3.0),
    )
    loaded = core.visual_documents.get("lab.test.edit")

    assert edited["revision"] == 2
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


class SelectedHeadlessCore(HeadlessCore):
    """Test-only selector/executor fixture; it never renders or activates a capability."""

    def __init__(self, database: Path):
        super().__init__(database)
        self.execution_calls = []

    def inspect_visual_backend_selection(self, task_spec):
        return {
            "status": "selected",
            "backend_id": "test.fake.visual.backend",
            "execution_performed": False,
        }

    def execute_image_task(self, *args, **kwargs):
        self.execution_calls.append((args, kwargs))
        return {
            "status": "delegated_to_test_fixture",
            "execution_performed": False,
        }


def test_visual_lab_delegates_provenance_only_after_test_selector_selects(tmp_path):
    core = SelectedHeadlessCore(tmp_path / "memory.sqlite3")
    lab = VisualDocumentLab(core)
    created = lab.create_demo("lab.test.positive-gate")

    report = lab.run(
        "lab.test.positive-gate",
        task_id="task.lab.positive-gate",
        execute=True,
        estimated_ram_mb=128,
        estimated_seconds=2.5,
    )

    assert len(core.execution_calls) == 1
    args, kwargs = core.execution_calls[0]
    assert args[0].task_id == "task.lab.positive-gate"
    assert kwargs["estimated_ram_mb"] == 128
    assert kwargs["estimated_seconds"] == 2.5
    assert kwargs["visual_provenance"].to_dict()["source_document_sha256"] == created["sha256"]
    assert report["execution"]["status"] == "delegated_to_test_fixture"
    assert report["execution"]["execution_performed"] is False
    assert report["capability_activation_performed"] is False


def test_visual_lab_requires_resource_estimates_before_delegation(tmp_path):
    core = SelectedHeadlessCore(tmp_path / "memory.sqlite3")
    lab = VisualDocumentLab(core)
    lab.create_demo("lab.test.missing-estimates")

    with pytest.raises(ValueError, match="estimated-ram-mb"):
        lab.run(
            "lab.test.missing-estimates",
            task_id="task.lab.missing-estimates",
            execute=True,
        )

    assert core.execution_calls == []


@pytest.mark.parametrize("document_exists", [True, False])
def test_visual_lab_cli_closes_core_after_success_or_command_error(
    tmp_path, monkeypatch, capsys, document_exists,
):
    instances = []
    document = SimpleNamespace(
        document_id="lab.cli.test",
        layers=(),
        elements=(),
        SCHEMA="mahoraga.visual_document.v1",
        to_dict=lambda: {"document_id": "lab.cli.test"},
    )
    stored = SimpleNamespace(
        document=document,
        revision=1,
        sha256="a" * 64,
        parent_sha256=None,
        status="ready",
    )

    class FakeVisualDocumentStore:
        def get(self, document_id):
            return stored if document_exists else None

        def list_revisions(self, document_id):
            return []

    class FakeCore:
        def __init__(self, root, store):
            self.visual_documents = FakeVisualDocumentStore()
            self.closed = False
            instances.append(self)

        def close(self):
            self.closed = True

    integration_module = ModuleType("agent.integration_core")
    integration_module.IntegratedCore = FakeCore
    monkeypatch.setitem(sys.modules, "agent.integration_core", integration_module)
    monkeypatch.setattr("agent.store.KnowledgeStore", lambda database: object())

    argv = [
        "--root", str(tmp_path),
        "--database", str(tmp_path / "cli.sqlite3"),
        "inspect",
        "--document-id", "lab.cli.test",
    ]
    if document_exists:
        assert visual_lab_main(argv) == 0
        assert '"document_id": "lab.cli.test"' in capsys.readouterr().out
    else:
        with pytest.raises(ValueError, match="não encontrado"):
            visual_lab_main(argv)

    assert len(instances) == 1
    assert instances[0].closed is True


def test_visual_lab_does_not_mask_executor_failure_or_report_success(tmp_path):
    core = SelectedHeadlessCore(tmp_path / "memory.sqlite3")
    lab = VisualDocumentLab(core)
    created = lab.create_demo("lab.test.executor-failure")
    calls = []

    def fail_execution(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("synthetic executor failure")

    core.execute_image_task = fail_execution
    with pytest.raises(RuntimeError, match="synthetic executor failure"):
        lab.run(
            "lab.test.executor-failure",
            task_id="task.lab.executor-failure",
            execute=True,
            estimated_ram_mb=128,
            estimated_seconds=2.5,
        )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0].task_id == "task.lab.executor-failure"
    assert kwargs["visual_provenance"].to_dict()["source_document_sha256"] == created["sha256"]


def test_visual_lab_edit_transform_preserves_concurrent_revision_with_cas(tmp_path, monkeypatch):
    lab, core = make_lab(tmp_path)
    lab.create_demo("lab.test.concurrent-edit")
    current = core.visual_documents.get("lab.test.concurrent-edit")
    assert current is not None
    concurrent_document = replace(current.document, title="Concurrent external edit")
    original_save = core.visual_documents.save
    injected = False

    def race_save(document, *, expected_parent_sha256=None):
        nonlocal injected
        if not injected:
            injected = True
            original_save(
                concurrent_document,
                expected_parent_sha256=current.sha256,
            )
        return original_save(
            document,
            expected_parent_sha256=expected_parent_sha256,
        )

    monkeypatch.setattr(core.visual_documents, "save", race_save)
    with pytest.raises(VisualDocumentConflictError):
        lab.edit_transform(
            "lab.test.concurrent-edit", "element.sphere", (4.0, 5.0, 6.0),
        )

    latest = core.visual_documents.get("lab.test.concurrent-edit")
    assert latest is not None
    assert latest.revision == 2
    assert latest.document.title == "Concurrent external edit"
    sphere = next(item for item in latest.document.elements if item.element_id == "element.sphere")
    assert sphere.transform.translation == (0.0, 0.0, 0.0)


def test_visual_lab_preserves_executor_cancellation_without_success_claim(tmp_path, monkeypatch):
    core = SelectedHeadlessCore(tmp_path / "memory.sqlite3")
    lab = VisualDocumentLab(core)
    lab.create_demo("lab.test.cancelled")
    calls = []

    def cancelled_executor(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "status": "cancelled",
            "execution_performed": False,
            "cancellation_reason": "cooperative_test_cancel",
        }

    monkeypatch.setattr(core, "execute_image_task", cancelled_executor)
    report = lab.run(
        "lab.test.cancelled",
        task_id="task.lab.cancelled",
        execute=True,
        estimated_ram_mb=128,
        estimated_seconds=2.5,
    )

    assert len(calls) == 1
    assert report["execution"]["status"] == "cancelled"
    assert report["execution"]["execution_performed"] is False
    assert report["execution"]["cancellation_reason"] == "cooperative_test_cancel"
    assert report["capability_activation_performed"] is False
    assert not (tmp_path / "artifacts" / "images").exists()


@pytest.mark.parametrize("document_exists", [True, False])
def test_visual_lab_cli_reports_cleanup_failure_without_masking_command_failure(
    tmp_path, monkeypatch, capsys, document_exists,
):
    instances = []
    document = SimpleNamespace(
        document_id="lab.cleanup.test",
        layers=(),
        elements=(),
        SCHEMA="mahoraga.visual_document.v1",
        to_dict=lambda: {"document_id": "lab.cleanup.test"},
    )
    stored = SimpleNamespace(
        document=document,
        revision=1,
        sha256="b" * 64,
        parent_sha256=None,
        status="ready",
    )

    class FakeVisualDocumentStore:
        def get(self, document_id):
            return stored if document_exists else None

        def list_revisions(self, document_id):
            return []

    class FakeCore:
        def __init__(self, root, store):
            self.visual_documents = FakeVisualDocumentStore()
            instances.append(self)

        def close(self):
            raise RuntimeError("synthetic cleanup failure")

    integration_module = ModuleType("agent.integration_core")
    integration_module.IntegratedCore = FakeCore
    monkeypatch.setitem(sys.modules, "agent.integration_core", integration_module)
    monkeypatch.setattr("agent.store.KnowledgeStore", lambda database: object())

    argv = [
        "--root", str(tmp_path),
        "--database", str(tmp_path / "cleanup.sqlite3"),
        "inspect",
        "--document-id", "lab.cleanup.test",
    ]

    if document_exists:
        with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
            visual_lab_main(argv)
        capsys.readouterr()
    else:
        with pytest.raises(ValueError, match="não encontrado") as captured:
            visual_lab_main(argv)
        assert any(
            "synthetic cleanup failure" in note
            for note in getattr(captured.value, "__notes__", ())
        )

    assert len(instances) == 1


@pytest.mark.parametrize("alias_kind", ["direct", "symlink", "hardlink"])
def test_visual_lab_cli_refuses_canonical_knowledge_database_alias(
    tmp_path, alias_kind,
):
    from scripts.visual_document_lab import _resolve_database_path

    canonical = tmp_path / "memory" / "mahoraga.sqlite3"
    canonical.parent.mkdir(parents=True)
    canonical.touch()

    if alias_kind == "direct":
        candidate = canonical
    else:
        candidate = tmp_path / f"{alias_kind}.sqlite3"
        if alias_kind == "symlink":
            candidate.symlink_to(canonical)
        else:
            candidate.hardlink_to(canonical)

    with pytest.raises(ValueError, match="banco canônico"):
        _resolve_database_path(tmp_path, candidate)

    # The safety check is read-only: it neither opens nor modifies the store.
    assert canonical.stat().st_size == 0



def test_visual_lab_refuses_repository_store_even_with_custom_root(tmp_path, monkeypatch):
    import scripts.visual_document_lab as visual_lab_module

    repository_root = tmp_path / "repository"
    canonical = repository_root / "memory" / "mahoraga.sqlite3"
    canonical.parent.mkdir(parents=True)
    canonical.touch()
    monkeypatch.setattr(visual_lab_module, "_REPOSITORY_ROOT", repository_root)

    with pytest.raises(ValueError, match="banco canônico"):
        visual_lab_module._resolve_database_path(tmp_path / "custom-root", canonical)

    assert canonical.stat().st_size == 0



def test_visual_lab_cli_rejects_canonical_database_before_opening_core(
    tmp_path, monkeypatch,
):
    canonical = tmp_path / "memory" / "mahoraga.sqlite3"
    canonical.parent.mkdir(parents=True)
    sentinel = b"canonical-store-must-remain-untouched"
    canonical.write_bytes(sentinel)

    class ForbiddenCore:
        def __init__(self, *args, **kwargs):
            pytest.fail("IntegratedCore must not open the canonical lab database")

    integration_module = ModuleType("agent.integration_core")
    integration_module.IntegratedCore = ForbiddenCore
    monkeypatch.setitem(sys.modules, "agent.integration_core", integration_module)
    monkeypatch.setattr(
        "agent.store.KnowledgeStore",
        lambda database: pytest.fail("KnowledgeStore must not open the canonical database"),
    )

    argv = [
        "--root", str(tmp_path),
        "--database", str(canonical),
        "inspect",
        "--document-id", "must.not.open",
    ]
    with pytest.raises(ValueError, match="banco canônico"):
        visual_lab_main(argv)

    assert canonical.read_bytes() == sentinel


def test_visual_lab_cli_refuses_canonical_database_before_store_or_core_initialization(
    tmp_path, monkeypatch,
):
    import scripts.visual_document_lab as visual_lab_module

    repository_root = tmp_path / "repository"
    canonical = repository_root / "memory" / "mahoraga.sqlite3"
    canonical.parent.mkdir(parents=True)
    canonical.touch()
    monkeypatch.setattr(visual_lab_module, "_REPOSITORY_ROOT", repository_root)

    class ForbiddenCore:
        def __init__(self, *args, **kwargs):
            pytest.fail("IntegratedCore must not be instantiated for the canonical database")

    integration_module = ModuleType("agent.integration_core")
    integration_module.IntegratedCore = ForbiddenCore
    monkeypatch.setitem(sys.modules, "agent.integration_core", integration_module)

    def forbidden_store(*args, **kwargs):
        pytest.fail("KnowledgeStore must not be initialized for the canonical database")

    monkeypatch.setattr("agent.store.KnowledgeStore", forbidden_store)
    with pytest.raises(ValueError, match="banco canônico"):
        visual_lab_main([
            "--root", str(tmp_path / "custom-root"),
            "--database", str(canonical),
            "inspect", "--document-id", "lab.guard.test",
        ])

    assert canonical.stat().st_size == 0
