from types import ModuleType
import sys

import pytest

from scripts.visual_document_lab import main as visual_lab_main


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
