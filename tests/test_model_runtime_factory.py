import json
from pathlib import Path

import pytest

from agent.model_runtime_factory import (
    EXPECTED_MODEL_SHA256,
    MODEL_ID,
    build_configured_model_generation_port,
)
from agent.model_runtime import AdaptiveModelBackend, ResourceRequest


class FakeHardware:
    def __init__(self, model_root):
        self.model_root = Path(model_root)

    def resource_snapshot(self):
        return {
            "captured_at": "test",
            "memory": {"values": {
                "MemAvailable": {"mb": 8192},
                "MemTotal": {"mb": 12288},
            }},
            "storage": {"project": {
                "path": str(self.model_root),
                "free_bytes": 8 * 1024 * 1024 * 1024,
            }},
            "battery": {"termux_api": {"data": {
                "percentage": 90, "status": "charging",
            }}},
            "thermal": {"status": "normal"},
        }

    def runtime_context(self):
        return {
            "app_foreground": True,
            "screen_interactive": True,
            "thermal_status": "normal",
            "read_only": True,
        }


class FakeStore:
    def __init__(self):
        self.events = []

    def record_event(self, event_type, payload):
        self.events.append((event_type, payload))


def write_config(root, **overrides):
    config_dir = Path(root) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema": "mahoraga.litert_model_runtime",
        "version": "1.0.0",
        "enabled": True,
        "model_id": MODEL_ID,
        "model_path": str((Path(root) / "qwen.litertlm").resolve()),
        "expected_sha256": EXPECTED_MODEL_SHA256,
        "backend": "cpu",
        "task_class": "interactive",
        "max_prompt_chars": 9000,
        "context_window_tokens": 4096,
        "max_output_chars": 16000,
        "runtime_overhead_mb": 768,
        "system_memory_reserve_mb": 512,
        "top_k": 20,
        "top_p": 0.95,
        "temperature": 0.6,
    }
    config.update(overrides)
    path = config_dir / "litert_model_runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_disabled_litert_config_keeps_existing_provider_untouched(tmp_path):
    write_config(tmp_path, enabled=False, model_path=None)
    result = build_configured_model_generation_port(
        tmp_path,
        hardware=FakeHardware(tmp_path),
        store=FakeStore(),
    )
    assert result is None


def test_enabled_litert_port_is_lazy_and_shares_hardware_and_store(tmp_path):
    model_path = tmp_path / "qwen.litertlm"
    model_path.write_bytes(b"fixture bytes; digest is checked only on load")
    write_config(tmp_path)
    hardware = FakeHardware(tmp_path)
    store = FakeStore()

    adapter = build_configured_model_generation_port(
        tmp_path,
        hardware=hardware,
        store=store,
    )

    assert adapter.enabled is True
    status = adapter.status()
    assert status["configured"] is True
    assert status["loaded"] is False
    assert status["operationally_verified"] is False
    assert adapter._runtime.loaded is False
    assert adapter._runtime.store is store
    assert adapter._runtime.admission.hardware is hardware
    assert isinstance(adapter._runtime.backend, AdaptiveModelBackend)
    assert adapter._runtime.backend.fallback is None

    request = adapter._request_factory(
        task_class="interactive",
        max_output_tokens=None,
        temperature=None,
    )
    assert isinstance(request, ResourceRequest)
    assert request.top_k == 20
    assert request.top_p == 0.95
    assert request.temperature == 0.6


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_sha256": "0" * 64}, "digest_not_approved"),
        ({"model_path": "relative/model.litertlm"}, "must_be_absolute"),
        ({"backend": "gpu"}, "not_device_validated"),
        ({"task_class": "background"}, "task_class_invalid"),
        ({"task_class": []}, "task_class_invalid"),
    ],
)
def test_enabled_litert_config_rejects_unapproved_values(tmp_path, override, message):
    model_path = tmp_path / "qwen.litertlm"
    model_path.write_bytes(b"fixture")
    write_config(tmp_path, **override)

    with pytest.raises(ValueError, match=message):
        build_configured_model_generation_port(
            tmp_path,
            hardware=FakeHardware(tmp_path),
            store=FakeStore(),
        )


def test_enabled_litert_config_requires_read_only_hardware_contract(tmp_path):
    model_path = tmp_path / "qwen.litertlm"
    model_path.write_bytes(b"fixture")
    write_config(tmp_path)

    with pytest.raises(ValueError, match="hardware_runtime_admission_contract"):
        build_configured_model_generation_port(
            tmp_path,
            hardware=object(),
            store=FakeStore(),
        )


def test_malformed_litert_config_fails_closed(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "litert_model_runtime.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="config_unreadable"):
        build_configured_model_generation_port(
            tmp_path,
            hardware=FakeHardware(tmp_path),
            store=FakeStore(),
        )



def test_enabled_litert_config_requires_existing_litertlm_artifact(tmp_path):
    write_config(tmp_path, model_path=str((tmp_path / "missing.litertlm").resolve()))

    with pytest.raises(ValueError, match="model_file_not_found_or_invalid"):
        build_configured_model_generation_port(
            tmp_path,
            hardware=FakeHardware(tmp_path),
            store=FakeStore(),
        )


def test_enabled_litert_config_validates_sampler_before_exposing_port(tmp_path):
    model_path = tmp_path / "qwen.litertlm"
    model_path.write_bytes(b"fixture")
    write_config(tmp_path, top_k=0)

    with pytest.raises(ValueError, match="top_k"):
        build_configured_model_generation_port(
            tmp_path,
            hardware=FakeHardware(tmp_path),
            store=FakeStore(),
        )
