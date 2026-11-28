from __future__ import annotations

import shutil
import sys

import pytest

from scripts import mahoraga_background_worker as worker


def _copy_manifest(root):
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    source = worker.ROOT / "config" / "capability_manifest.json"
    target = config_dir / "capability_manifest.json"
    shutil.copyfile(source, target)
    return target


def _block_heavy_imports(monkeypatch):
    for module_name in (
        "agent.integration_core",
        "agent.background_work_queue",
        "agent.android_workmanager_wake",
    ):
        monkeypatch.setitem(sys.modules, module_name, None)


def test_disabled_manifest_defers_before_core_store_or_android_import(tmp_path, monkeypatch):
    _copy_manifest(tmp_path)
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    _block_heavy_imports(monkeypatch)

    result = worker.run_worker_once()

    assert result["status"] == "deferred"
    assert result["reason"] == "capability_disabled_in_manifest"
    assert result["execution_performed"] is False
    assert result["completion_receipt_valid"] is False
    assert result["queue"] == {
        "status": "not_opened",
        "active_items": None,
        "execution_performed": False,
    }
    assert result["wake_schedule"] == {
        "status": "not_requested",
        "delay_seconds": None,
    }


def test_invalid_manifest_blocks_before_core_initialization(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "capability_manifest.json").write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    _block_heavy_imports(monkeypatch)

    result = worker.run_worker_once()

    assert result["status"] == "blocked"
    assert result["reason"] == "capability_manifest_unavailable_or_invalid"
    assert result["execution_performed"] is False
    assert result["queue"]["status"] == "not_opened"
    assert result["wake_schedule"]["status"] == "not_requested"


def test_missing_manifest_blocks_before_core_initialization(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    _block_heavy_imports(monkeypatch)

    result = worker.run_worker_once()

    assert result["status"] == "blocked"
    assert result["reason"] == "capability_manifest_unavailable_or_invalid"
    assert result["execution_performed"] is False
    assert result["queue"]["status"] == "not_opened"


@pytest.mark.parametrize("epoch", [float("nan"), float("inf"), float("-inf"), -1, True])
def test_poll_descriptor_rejects_nonfinite_negative_or_boolean_epoch(epoch):
    with pytest.raises(ValueError):
        worker.build_poll_task_descriptor(epoch)


def test_poll_descriptor_accepts_finite_nonnegative_epoch():
    descriptor = worker.build_poll_task_descriptor(900)

    assert descriptor["task_id"] == "internal-inquiry-poll:1"
    assert descriptor["capability"] == "internal.adopt_next_inquiry"
    assert descriptor["estimated_runtime_seconds"] == 8
    assert descriptor["estimated_ram_mb"] == 64
