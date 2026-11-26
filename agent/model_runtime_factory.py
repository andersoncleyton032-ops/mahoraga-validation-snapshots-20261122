"""Explicit, fail-closed composition of the governed local LiteRT runtime.

The model is constructed only when a separate LiteRT configuration explicitly
enables it. The default IntegratedCore path remains the existing disabled
loopback adapter. No model file is loaded during composition.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .model_generation_port import ModelRuntimeGenerationAdapter
from .model_runtime import (
    AdaptiveModelBackend,
    ModelResourcePolicy,
    ModelRuntime,
    ModelSpec,
    ResourceRequest,
)

MODEL_ID = "Qwen3-1.7B_dynamic_wi4b32_afp32"
EXPECTED_MODEL_SHA256 = "2a72330b504a6596d53a2c00923c57173b10f1b83e6a541213ffec08d1fc5de8"
CONFIG_RELATIVE_PATH = Path("config/litert_model_runtime.json")


def build_configured_model_generation_port(
    root: str | Path,
    *,
    hardware: Any,
    store: Any,
    config_path: str | Path | None = None,
):
    """Return a lazy LiteRT generation adapter only after explicit opt-in.

    Missing or disabled configuration returns None so IntegratedCore can keep
    its existing loopback adapter. Invalid enabled configuration raises and
    fails closed; it never silently falls back to another provider.
    """
    root_path = Path(root).expanduser().resolve()
    selected_config = (
        Path(config_path).expanduser()
        if config_path is not None
        else root_path / CONFIG_RELATIVE_PATH
    )
    if not selected_config.is_absolute():
        selected_config = (root_path / selected_config).resolve()
    if not selected_config.is_file():
        return None

    try:
        config = json.loads(selected_config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("litert_model_runtime_config_unreadable") from exc
    if not isinstance(config, dict):
        raise ValueError("litert_model_runtime_config_invalid")
    if config.get("schema") != "mahoraga.litert_model_runtime":
        raise ValueError("litert_model_runtime_schema_invalid")
    if config.get("version") != "1.0.0":
        raise ValueError("litert_model_runtime_version_unsupported")
    enabled = config.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("litert_model_runtime_enabled_must_be_boolean")
    if enabled is False:
        return None

    model_id = config.get("model_id")
    if model_id != MODEL_ID:
        raise ValueError("litert_model_id_not_approved")
    expected_sha256 = config.get("expected_sha256")
    if expected_sha256 != EXPECTED_MODEL_SHA256:
        raise ValueError("litert_model_digest_not_approved")

    model_path_value = config.get("model_path")
    if not isinstance(model_path_value, str) or not model_path_value.strip():
        raise ValueError("litert_model_path_required")
    model_path = Path(model_path_value).expanduser()
    if not model_path.is_absolute():
        raise ValueError("litert_model_path_must_be_absolute")
    if model_path.suffix.lower() != ".litertlm" or not model_path.is_file():
        raise ValueError("litert_model_file_not_found_or_invalid")

    backend_name = config.get("backend", "cpu")
    if backend_name != "cpu":
        raise ValueError("litert_backend_not_device_validated")

    task_class = config.get("task_class", "interactive")
    if not isinstance(task_class, str) or task_class not in {
        "interactive", "reasoning", "maintenance"
    }:
        raise ValueError("litert_task_class_invalid")

    runtime_context_reader = getattr(hardware, "runtime_context", None)
    resource_snapshot_reader = getattr(hardware, "resource_snapshot", None)
    if not callable(runtime_context_reader) or not callable(resource_snapshot_reader):
        raise ValueError("hardware_runtime_admission_contract_unavailable")
    if store is None:
        raise ValueError("shared_knowledge_store_required")

    cache_dir_value = config.get("cache_dir")
    cache_dir = None
    if cache_dir_value is not None:
        if not isinstance(cache_dir_value, str) or not cache_dir_value.strip():
            raise ValueError("litert_cache_dir_invalid")
        cache_dir = Path(cache_dir_value).expanduser()
        if not cache_dir.is_absolute():
            raise ValueError("litert_cache_dir_must_be_absolute")

    spec = ModelSpec(
        model_id=model_id,
        model_path=model_path,
        format="litertlm",
        backend_name=backend_name,
        expected_sha256=expected_sha256,
        max_prompt_chars=config.get("max_prompt_chars", 9000),
        context_window_tokens=config.get("context_window_tokens", 4096),
        max_output_chars=config.get("max_output_chars", 16000),
        cache_dir=cache_dir,
        estimated_peak_ram_mb=config.get("estimated_peak_ram_mb"),
        runtime_overhead_mb=config.get("runtime_overhead_mb", 768),
        system_memory_reserve_mb=config.get("system_memory_reserve_mb", 512),
        minimum_free_storage_mb=config.get("minimum_free_storage_mb"),
    )
    admission = ModelResourcePolicy(
        hardware,
        runtime_context_reader=runtime_context_reader,
    )
    backend = AdaptiveModelBackend(
        backend_name=backend_name,
        cache_dir=spec.cache_dir,
        allow_android_fallback=False,
    )
    runtime = ModelRuntime(
        spec,
        backend=backend,
        admission=admission,
        store=store,
    )

    top_k = config.get("top_k", 20)
    top_p = config.get("top_p", 0.95)
    default_temperature = config.get("temperature", 0.6)
    # Validate the configured sampler before exposing the port to IntegratedCore.
    ResourceRequest(top_k=top_k, top_p=top_p, temperature=default_temperature)

    def request_factory(
        *,
        task_class: str,
        max_output_tokens: int | None,
        temperature: float | None,
    ):
        planner = runtime.budget_selector
        planned = planner.for_task(spec, task_class)
        return replace(
            planned,
            max_output_tokens=(
                max_output_tokens
                if max_output_tokens is not None
                else planned.max_output_tokens
            ),
            top_k=top_k,
            top_p=top_p,
            temperature=(
                temperature if temperature is not None else default_temperature
            ),
        )

    return ModelRuntimeGenerationAdapter(
        runtime,
        request_factory,
        enabled=True,
        task_class=task_class,
    )
