from experiments.architecture_observer import (
    ArchitectureObservationError,
    ArchitectureObserver,
    inspect_architecture,
)


def make_project(root):
    (root / "agent").mkdir()
    (root / "experiments").mkdir()
    (root / "tests").mkdir()
    (root / "agent" / "__init__.py").write_text("", encoding="utf-8")
    (root / "agent" / "alpha.py").write_text(
        "from .beta import Beta\nclass Alpha: pass\n", encoding="utf-8"
    )
    (root / "agent" / "beta.py").write_text(
        "from .alpha import Alpha\nclass Beta: pass\n", encoding="utf-8"
    )
    (root / "experiments" / "trial.py").write_text(
        "def run():\n    return True\n", encoding="utf-8"
    )
    (root / "tests" / "test_alpha.py").write_text(
        "from agent.alpha import Alpha\ndef test_alpha(): assert Alpha\n",
        encoding="utf-8",
    )


def test_observer_reports_inventory_hashes_and_static_import_cycles(tmp_path):
    make_project(tmp_path)
    report = inspect_architecture(tmp_path)

    assert report["status"] == "completed"
    assert report["inventory"]["parsed_files"] == 5
    assert report["inventory"]["dependency_graph"]["agent.alpha"] == ["agent.beta"]
    assert report["inventory"]["dependency_graph"]["agent.beta"] == ["agent.alpha"]
    assert {
        item["kind"] for item in report["findings"]
    } >= {"internal_import_cycle", "agent_module_without_detected_direct_test_import"}
    alpha = next(item for item in report["files"] if item["path"] == "agent/alpha.py")
    assert len(alpha["sha256"]) == 64
    assert report["execution_performed"] is False
    assert report["filesystem_modified"] is False


def test_observer_is_deterministic_for_unchanged_source(tmp_path):
    make_project(tmp_path)
    first = inspect_architecture(tmp_path)
    second = inspect_architecture(tmp_path)
    assert first == second


def test_observer_reports_syntax_errors_without_importing_source(tmp_path):
    make_project(tmp_path)
    (tmp_path / "agent" / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    report = inspect_architecture(tmp_path)
    assert report["status"] == "partial"
    assert report["inventory"]["parse_errors"] == 1
    assert report["findings"][0]["kind"] == "source_parse_error"


def test_observer_enforces_file_and_byte_limits(tmp_path):
    make_project(tmp_path)
    report = ArchitectureObserver(tmp_path, max_files=2).inspect()
    assert report["inventory"]["truncated"] is True
    assert report["status"] == "partial"

    limited = ArchitectureObserver(tmp_path, max_file_bytes=1).inspect()
    assert limited["inventory"]["oversized_files"] == 5
    assert limited["status"] == "partial"


def test_observer_rejects_invalid_roots_and_limits(tmp_path):
    import pytest

    with pytest.raises(ArchitectureObservationError):
        ArchitectureObserver(tmp_path / "missing")
    with pytest.raises(ArchitectureObservationError):
        ArchitectureObserver(tmp_path, max_files=True)
    with pytest.raises(ArchitectureObservationError):
        ArchitectureObserver(tmp_path, max_file_bytes=0)


def test_observer_does_not_follow_symlinked_files_or_directories(tmp_path):
    import os
    import pytest

    make_project(tmp_path)
    outside = tmp_path.parent / "outside_mahoraga_module.py"
    outside.write_text("raise RuntimeError('must not be executed')\n", encoding="utf-8")
    try:
        (tmp_path / "agent" / "outside.py").symlink_to(outside)
        (tmp_path / "agent" / "linked_dir").symlink_to(tmp_path / "tests", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported in this environment")

    report = inspect_architecture(tmp_path)
    paths = {item["path"] for item in report["files"]}
    assert "agent/outside.py" not in paths
    assert not any(path.startswith("agent/linked_dir/") for path in paths)
    assert outside.read_text(encoding="utf-8").startswith("raise RuntimeError")
