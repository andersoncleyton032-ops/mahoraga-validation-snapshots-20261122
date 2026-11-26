import hashlib
import json
import sys
import types
import time
import pytest

import agent.model_runtime as model_runtime_module
from pathlib import Path
from agent.model_runtime import (
    AdaptiveBudgetPlanner, AdaptiveModelBackend, AndroidContentProviderBackend,
    LiteRTLMBackend, ModelUnavailableError, ModelInferenceCancelled, ModelDeadlineExceeded,
    ModelAdmissionError, ModelResourcePolicy,
    ModelRuntime, ModelSpec, ModelRuntimeError, ResourceRequest,
)

class FakeHardware:
    def __init__(self, ram_mb=4096, storage_mb=8192, storage_path="/", total_ram_mb=12288):
        self.ram_mb = ram_mb
        self.storage_mb = storage_mb
        self.storage_path = str(storage_path)
        self.total_ram_mb = total_ram_mb
    def resource_snapshot(self):
        return {
            "captured_at": "test",
            "memory": {"values": {
                "MemAvailable": {"mb": self.ram_mb},
                "MemTotal": {"mb": self.total_ram_mb},
            }},
            "storage": {"model_mount": {
                "path": self.storage_path,
                "free_bytes": self.storage_mb * 1024 * 1024,
            }},
        }

class FakeBackend:
    def __init__(self):
        self.loaded = False
        self.closed = False
        self.prompts = []
    def load(self, model_path):
        self.loaded = True
        self.closed = False
    def generate(self, prompt, *, request):
        self.prompts.append(prompt)
        return "resposta local"
    def close(self):
        self.closed = True
        self.loaded = False

def make_runtime(tmp_path, *, ram=4096, storage=8192, backend=None, context=None):
    model = tmp_path / "qwen3-1.7b-int4.litertlm"
    model.write_bytes(b"model-fixture")
    hardware = FakeHardware(ram, storage, tmp_path)
    policy = ModelResourcePolicy(hardware, lambda: context or {
        "app_foreground": True, "screen_interactive": True, "thermal_status": "light",
    })
    fake = backend or FakeBackend()
    return ModelRuntime(
        ModelSpec("qwen3-1.7b-int4", model, cache_dir=tmp_path), fake, policy
    ), fake

def test_model_runtime_is_lazy_and_serialized(tmp_path):
    runtime, backend = make_runtime(tmp_path)
    assert runtime.loaded is False
    assert backend.loaded is False
    assert runtime.generate("Olá") == "resposta local"
    assert runtime.loaded is True
    assert backend.prompts == ["Olá"]
    runtime.close()
    assert backend.closed is True

@pytest.mark.parametrize(("ram", "storage", "reason"), [
    (256, 8192, "insufficient_available_ram"),
    (4096, 32, "insufficient_free_storage"),
])
def test_model_load_is_denied_when_resources_are_insufficient(tmp_path, ram, storage, reason):
    runtime, backend = make_runtime(tmp_path, ram=ram, storage=storage)
    result = runtime.load()
    assert result["loaded"] is False
    assert result["admission"]["reason"] == reason
    assert backend.loaded is False

def test_model_load_requires_resource_policy(tmp_path):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    runtime = ModelRuntime(ModelSpec("qwen", model), FakeBackend())
    assert runtime.load()["reason"] == "resource_admission_not_configured"

def test_model_load_rejects_background_context(tmp_path):
    runtime, backend = make_runtime(
        tmp_path, context={"app_foreground": False, "screen_interactive": True}
    )
    result = runtime.load()
    assert result["loaded"] is False
    assert result["admission"]["reason"] == "foreground_state_not_confirmed"
    assert backend.loaded is False

def test_model_file_sha256_is_verified(tmp_path):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    spec = ModelSpec("qwen", model, expected_sha256=hashlib.sha256(b"other").hexdigest())
    runtime = ModelRuntime(
        ModelSpec("qwen", model, expected_sha256=hashlib.sha256(b"other").hexdigest(),
                  cache_dir=model.parent),
        FakeBackend(), ModelResourcePolicy(FakeHardware(storage_path=model.parent))
    )
    assert runtime.load()["reason"] == "sha256_mismatch"

def test_prompt_and_output_limits_are_enforced(tmp_path):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    spec = ModelSpec("qwen", model, max_prompt_chars=3, max_output_chars=4)
    runtime = ModelRuntime(
        spec, FakeBackend(), ModelResourcePolicy(FakeHardware(), lambda: {
            "app_foreground": True, "screen_interactive": True, "thermal_status": "light",
        })
    )
    with pytest.raises(ValueError, match="max_prompt_chars"):
        runtime.generate("long")
    assert runtime.generate("ok") == "resp"
    runtime.close()

def test_runtime_close_is_idempotent_and_blocks_future_use(tmp_path):
    runtime, backend = make_runtime(tmp_path)
    runtime.close()
    runtime.close()
    with pytest.raises(ModelRuntimeError, match="encerrado"):
        runtime.generate("Olá")
    assert backend.closed is False

def test_litert_backend_import_is_lazy():
    backend = LiteRTLMBackend()
    assert backend._engine is None
    assert backend._engine_manager is None
    assert backend._litert_module is None


def test_storage_on_unrelated_mount_does_not_admit_model(tmp_path):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    hardware = FakeHardware(storage_mb=8192, storage_path=tmp_path / "other")
    runtime = ModelRuntime(
        ModelSpec("qwen", model), FakeBackend(), ModelResourcePolicy(hardware),
    )
    result = runtime.load()
    assert result["loaded"] is False
    assert result["admission"]["reason"] == "free_storage_unknown"


def test_unknown_foreground_state_fails_closed(tmp_path):
    runtime, backend = make_runtime(
        tmp_path, context={"app_foreground": None, "screen_interactive": True}
    )
    result = runtime.load()
    assert result["loaded"] is False
    assert result["admission"]["reason"] == "foreground_state_not_confirmed"
    assert backend.loaded is False


def test_inference_rechecks_thermal_state_after_model_is_loaded(tmp_path):
    context = {
        "app_foreground": True,
        "screen_interactive": True,
        "thermal_status": "light",
    }
    runtime, backend = make_runtime(tmp_path, context=context)
    assert runtime.load()["loaded"] is True
    context["thermal_status"] = "severe"
    with pytest.raises(ModelAdmissionError, match="thermal_state_blocks_model_load"):
        runtime.generate("Olá")
    assert backend.prompts == []
    runtime.close()


def test_inference_rechecks_available_ram_after_model_is_loaded(tmp_path):
    runtime, backend = make_runtime(tmp_path, ram=4096)
    assert runtime.load()["loaded"] is True
    runtime.admission.hardware.ram_mb = 256
    with pytest.raises(ModelAdmissionError, match="insufficient_available_ram"):
        runtime.generate("Olá")
    assert backend.prompts == []
    runtime.close()


def test_default_memory_budget_is_estimated_from_model_not_fixed_3_gib(tmp_path):
    runtime, backend = make_runtime(tmp_path, ram=1900)
    result = runtime.load()
    assert result["loaded"] is True
    assert result["admission"]["required_ram_mb"] < 1900
    runtime.close()


def test_task_request_can_raise_memory_budget_for_large_reasoning_task(tmp_path):
    runtime, backend = make_runtime(tmp_path, ram=4096)
    request = ResourceRequest(
        task_class="reasoning", priority=90, estimated_peak_ram_mb=5000
    )
    result = runtime.load(request=request)
    assert result["loaded"] is False
    assert result["admission"]["reason"] == "insufficient_available_ram"
    assert backend.loaded is False


def test_task_request_can_set_its_own_deadline(tmp_path):
    runtime, backend = make_runtime(tmp_path)
    request = ResourceRequest(task_class="interactive", max_duration_seconds=17.5)
    assert runtime.generate("Olá", request=request) == "resposta local"
    runtime.close()


def test_budget_selector_is_used_when_caller_does_not_supply_request(tmp_path):
    selected = ResourceRequest(task_class="reasoning", priority=80,
                               estimated_peak_ram_mb=1200)
    runtime, backend = make_runtime(tmp_path)
    runtime.budget_selector = lambda spec: selected
    assert runtime.generate("Analise",) == "resposta local"
    runtime.close()


def test_background_execution_requires_explicit_task_class_and_opt_in(tmp_path):
    runtime, backend = make_runtime(
        tmp_path, context={"app_foreground": False, "screen_interactive": False}
    )
    denied = runtime.load()
    assert denied["loaded"] is False
    request = ResourceRequest(task_class="background", allow_background=True)
    allowed = runtime.load(request=request)
    assert allowed["loaded"] is True
    runtime.close()


def test_runtime_reports_deadline_overrun_when_backend_cannot_cancel(tmp_path):
    class SlowBackend(FakeBackend):
        def generate(self, prompt, *, request):
            time.sleep(0.03)
            return "late response"

    runtime, _ = make_runtime(tmp_path, backend=SlowBackend())
    request = ResourceRequest(max_duration_seconds=0.01)
    with pytest.raises(ModelRuntimeError, match="ultrapassou"):
        runtime.generate("Olá", request=request)
    runtime.close()


def test_adaptive_budget_planner_assigns_distinct_task_durations(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    planner = AdaptiveBudgetPlanner(runtime.admission.hardware)
    interactive = planner.for_task(runtime.spec, "interactive")
    reasoning = planner.for_task(runtime.spec, "reasoning")
    maintenance = planner.for_task(runtime.spec, "maintenance")
    assert interactive.max_duration_seconds < reasoning.max_duration_seconds
    assert reasoning.estimated_peak_ram_mb > interactive.estimated_peak_ram_mb
    assert maintenance.max_duration_seconds > reasoning.max_duration_seconds




@pytest.mark.parametrize(
    ("task_class", "ceiling"),
    [
        ("interactive", 60.0),
        ("reasoning", 240.0),
        ("maintenance", 360.0),
        ("background", 600.0),
    ],
)
def test_resource_request_clamps_explicit_deadline_to_android_task_class_ceiling(
    task_class, ceiling
):
    request = ResourceRequest(
        task_class=task_class,
        allow_background=(task_class == "background"),
        max_duration_seconds=1_000_000_000.0,
    )

    assert request.max_duration_seconds == ceiling


def test_adaptive_planner_caps_override_before_priority_and_thermal_derating(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    planner = AdaptiveBudgetPlanner(
        runtime.admission.hardware,
        runtime_context_reader=lambda: {"thermal_status": "moderate"},
    )

    request = planner.for_task(
        runtime.spec,
        "reasoning",
        priority=100,
        requested_duration_seconds=1_000_000_000.0,
    )

    # 240s is the reasoning hard ceiling; priority cannot raise it further,
    # and the moderate-thermal derating still applies afterward.
    assert request.max_duration_seconds == 180.0


def test_adaptive_budget_planner_reduces_duration_on_low_battery(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    snapshot = {
        "memory": {"values": {"MemAvailable": {"mb": 8192}}},
        "storage": {"mount": {"path": str(tmp_path), "free_bytes": 8192 * 1024 * 1024}},
        "battery": {"termux_api": {"data": {"percentage": 100, "status": "DISCHARGING"}}},
    }
    runtime.admission.hardware.resource_snapshot = lambda: snapshot
    planner = AdaptiveBudgetPlanner(runtime.admission.hardware)
    normal = planner.for_task(runtime.spec, "reasoning")
    snapshot["battery"]["termux_api"]["data"]["percentage"] = 10
    low_battery = planner.for_task(runtime.spec, "reasoning")
    assert low_battery.max_duration_seconds < normal.max_duration_seconds


def test_budget_planner_accepts_explicit_task_time_override(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    planner = AdaptiveBudgetPlanner(runtime.admission.hardware)
    request = planner.for_task(runtime.spec, "reasoning", requested_duration_seconds=47)
    assert 0 < request.max_duration_seconds <= 47


def test_model_unloads_on_resource_denial_and_can_reload_later(tmp_path):
    runtime, backend = make_runtime(tmp_path, ram=4096)
    assert runtime.load()["loaded"] is True
    runtime.admission.hardware.ram_mb = 128
    with pytest.raises(ModelAdmissionError):
        runtime.generate("primeira chamada")
    assert runtime.loaded is False
    assert backend.loaded is False
    runtime.admission.hardware.ram_mb = 4096
    assert runtime.generate("segunda chamada") == "resposta local"
    assert runtime.loaded is True
    assert backend.prompts == ["segunda chamada"]
    runtime.close()


def test_inference_does_not_require_free_storage_after_model_is_loaded(tmp_path):
    runtime, backend = make_runtime(tmp_path)
    assert runtime.load()["loaded"] is True
    runtime.admission.hardware.resource_snapshot = lambda: {
        "memory": {"values": {"MemAvailable": {"mb": 4096}}},
        "storage": {},
    }
    assert runtime.generate("sem escrita em disco") == "resposta local"
    runtime.close()


def test_task_request_cannot_lower_estimated_peak_memory_floor(tmp_path):
    runtime, backend = make_runtime(tmp_path, ram=1000)
    request = ResourceRequest(
        task_class="interactive",
        estimated_peak_ram_mb=1,
        minimum_available_ram_mb=1,
    )
    result = runtime.load(request=request)
    assert result["loaded"] is False
    assert result["admission"]["required_ram_mb"] > 1000
    assert backend.loaded is False


def test_inference_uses_incremental_headroom_not_full_model_load_peak(tmp_path):
    runtime, backend = make_runtime(tmp_path, ram=4096)
    assert runtime.load()["loaded"] is True
    runtime.admission.hardware.ram_mb = 1100
    assert runtime.generate("modelo residente") == "resposta local"
    assert backend.prompts == ["modelo residente"]
    runtime.close()


def test_reasoning_budget_can_raise_incremental_memory_without_changing_load_peak(tmp_path):
    runtime, backend = make_runtime(tmp_path, ram=4096)
    assert runtime.load()["loaded"] is True
    runtime.admission.hardware.ram_mb = 1000
    request = ResourceRequest(
        task_class="reasoning", estimated_additional_ram_mb=1600
    )
    with pytest.raises(ModelAdmissionError, match="insufficient_available_ram"):
        runtime.generate("raciocinio profundo", request=request)
    assert backend.prompts == []
    runtime.close()


def test_android_bundle_parser_handles_status_and_base64_payload():
    output = (
        "Result: Bundle[{status=completed, request_id=abc123, "
        "text_b64=SGVsbG8sIE1haG9yYWdhIQ==}]"
    )
    assert AndroidContentProviderBackend._bundle_value(output, "status") == "completed"
    assert AndroidContentProviderBackend._bundle_value(output, "request_id") == "abc123"
    assert AndroidContentProviderBackend._bundle_value(
        output, "text_b64"
    ) == "SGVsbG8sIE1haG9yYWdhIQ=="


def test_android_bundle_parser_handles_end_of_bundle_status():
    output = "Result: Bundle[{status=loaded}]"
    assert AndroidContentProviderBackend._bundle_value(output, "status") == "loaded"


def test_runtime_detects_android_style_external_unload_and_reloads(tmp_path):
    class HealthAwareBackend(FakeBackend):
        def is_loaded(self):
            return self.loaded

    runtime, backend = make_runtime(tmp_path, backend=HealthAwareBackend())
    assert runtime.generate("primeiro") == "resposta local"
    assert runtime.loaded is True
    backend.loaded = False
    assert runtime.generate("depois do trim memory") == "resposta local"
    assert runtime.loaded is True
    assert backend.prompts == ["primeiro", "depois do trim memory"]
    runtime.close()


def test_android_backend_reads_provider_loaded_state(monkeypatch):
    backend = AndroidContentProviderBackend()
    monkeypatch.setattr(
        backend, "_call",
        lambda method, arg=None, timeout_seconds=15.0:
            "Result: Bundle[{loaded=true, lifecycle_status=loaded}]",
    )
    assert backend.is_loaded() is True


def test_resource_request_rejects_non_finite_duration():
    with pytest.raises(ValueError, match="finito e positivo"):
        ResourceRequest(max_duration_seconds=float("nan"))


def test_thinking_can_be_disabled_for_simple_tasks():
    request = ResourceRequest(task_class="interactive", thinking_token_budget=0)
    assert request.thinking_token_budget == 0


def test_model_context_budget_rejects_generation_that_leaves_no_input_room(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    request = ResourceRequest(thinking_token_budget=2048, max_output_tokens=2048)
    with pytest.raises(ValueError, match="janela de contexto"):
        runtime.generate("Olá", request=request)


def test_adaptive_planner_assigns_reasoning_and_output_token_budgets(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    planner = AdaptiveBudgetPlanner(runtime.admission.hardware)
    simple = planner.for_task(runtime.spec, "interactive")
    reasoning = planner.for_task(runtime.spec, "reasoning")
    assert simple.thinking_token_budget == 256
    assert simple.max_output_tokens == 512
    assert reasoning.thinking_token_budget == 1024
    assert reasoning.max_output_tokens == 1024


def test_python_litert_backend_uses_fresh_context_managed_conversation_per_request(
    tmp_path, monkeypatch
):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    state = {
        "conversations": [],
        "engine_closed": False,
        "engine_options": None,
        "slow_stream": False,
    }

    class FakeConversation:
        def __init__(self, config):
            self.config = config
            self.closed = False
            self.cancelled = False
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            self.closed = True
        def cancel_process(self):
            self.cancelled = True
        def send_message_async(self, prompt):
            self.last_prompt = prompt
            rendered = prompt if isinstance(prompt, str) else json.dumps(prompt)
            if state["slow_stream"]:
                time.sleep(0.02)
            yield {"content": [{"type": "text", "text": "resposta:" + rendered}]}

    class FakeEngine:
        def __init__(self, path, **options):
            state["engine_options"] = options
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            state["engine_closed"] = True
        def create_conversation(self, **config):
            conversation = FakeConversation(config)
            state["conversations"].append(conversation)
            return conversation

    fake_module = types.SimpleNamespace(
        Backend=types.SimpleNamespace(CPU=lambda: "cpu", GPU=lambda: "gpu"),
        Engine=FakeEngine,
        ThinkingConfig=lambda **kwargs: kwargs,
        SamplerConfig=lambda **kwargs: kwargs,
    )
    monkeypatch.setitem(sys.modules, "litert_lm", fake_module)

    backend = LiteRTLMBackend(cache_dir=tmp_path)
    backend.load(model)
    request = ResourceRequest(task_class="interactive")
    assert backend.generate("um", request=request) == "resposta:um"
    assert backend.generate("dois", request=request) == "resposta:dois"
    structured_prompt = json.dumps({
        "format": "mahoraga_messages_v1",
        "messages": [
            {"role": "system", "content": "Você é Mahoraga."},
            {"role": "user", "content": "Pergunta anterior."},
            {"role": "assistant", "content": "Resposta anterior."},
            {"role": "user", "content": "Pergunta atual."},
        ],
    })
    backend.generate(structured_prompt, request=request)
    assert len(state["conversations"]) == 3
    assert all(item.closed for item in state["conversations"])
    structured_conversation = state["conversations"][2]
    assert structured_conversation.config["messages"] == [
        {"role": "system", "content": [{"type": "text", "text": "Você é Mahoraga."}]},
        {"role": "user", "content": [{"type": "text", "text": "Pergunta anterior."}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Resposta anterior."}]},
    ]
    assert structured_conversation.last_prompt == {
        "role": "user",
        "content": [{"type": "text", "text": "Pergunta atual."}],
    }
    assert structured_conversation.config["sampler_config"] == {
        "top_k": 20, "top_p": 0.95, "temperature": 0.6,
    }
    assert structured_conversation.config["automatic_tool_calling"] is False
    assert structured_conversation.config["max_output_tokens"] == 768
    assert state["engine_options"]["backend"] == "cpu"
    backend.close()
    assert state["engine_closed"] is True


@pytest.mark.parametrize("failure_stage", ["enter", "initialize"])
def test_litert_engine_partial_initialization_is_cleaned_up(
    tmp_path, monkeypatch, failure_stage
):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    state = {"close_calls": 0}

    class EngineBase:
        def __init__(self, _path, **_options):
            pass

        def close(self):
            state["close_calls"] += 1

    if failure_stage == "enter":
        class FakeEngine(EngineBase):
            def __enter__(self):
                raise RuntimeError("native enter failed")
    else:
        class FakeEngine(EngineBase):
            def initialize(self):
                raise RuntimeError("native initialize failed")

    fake_module = types.SimpleNamespace(
        Backend=types.SimpleNamespace(CPU=lambda: "cpu", GPU=lambda: "gpu"),
        Engine=FakeEngine,
    )
    monkeypatch.setitem(sys.modules, "litert_lm", fake_module)

    backend = LiteRTLMBackend(cache_dir=tmp_path)
    with pytest.raises(ModelUnavailableError, match="não inicializou"):
        backend.load(model)

    assert backend.is_loaded() is False
    assert backend._engine_manager is None
    assert backend._engine_context is False
    assert backend._litert_module is None
    assert state["close_calls"] == 1
    backend.close()
    assert state["close_calls"] == 1


def test_adaptive_backend_reloads_when_active_provider_loses_health(tmp_path):
    class FlakyBackend:
        def __init__(self):
            self.loaded = False
            self.load_calls = 0
            self.close_calls = 0

        def load(self, _model_path):
            self.load_calls += 1
            self.loaded = True

        def is_loaded(self):
            return self.loaded

        def close(self):
            self.close_calls += 1
            self.loaded = False

        def generate(self, _prompt, *, request):
            return "ok"

    primary = FlakyBackend()
    backend = AdaptiveModelBackend(primary=primary, allow_android_fallback=False)
    model_path = tmp_path / "qwen.litertlm"

    backend.load(model_path)
    assert backend.is_loaded() is True
    assert primary.load_calls == 1

    # Simulate native engine loss while the wrapper still holds its reference.
    primary.loaded = False
    backend.load(model_path)

    assert primary.close_calls == 1
    assert primary.load_calls == 2
    assert backend.is_loaded() is True


def test_adaptive_backend_falls_back_to_android_provider_when_python_api_fails(tmp_path):
    class FailedPrimary:
        def load(self, model_path):
            raise ModelUnavailableError("python wheel unavailable")
    class WorkingFallback(FakeBackend):
        pass

    fallback = WorkingFallback()
    backend = AdaptiveModelBackend(primary=FailedPrimary(), fallback=fallback)
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    backend.load(model)
    assert backend.active is fallback
    assert backend.is_loaded() is True
    backend.close()
    assert fallback.closed is True


def test_runtime_uses_adaptive_interactive_budget_when_caller_omits_request(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    request = runtime._select_request(None)
    assert request.task_class == "interactive"
    assert request.max_duration_seconds is not None
    assert request.thinking_token_budget == 256
    assert request.max_output_tokens == 512


def test_runtime_fills_missing_deadline_for_explicit_task_class(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    request = runtime._select_request(ResourceRequest(task_class="reasoning"))
    assert request.max_duration_seconds == 120.0
    assert request.duration_policy_applied is True


def test_adaptive_planner_scales_time_budget_by_priority(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    planner = AdaptiveBudgetPlanner(runtime.admission.hardware, lambda: {
        "thermal_status": "light",
        "app_foreground": True,
        "screen_interactive": True,
    })
    low = planner.for_task(runtime.spec, "reasoning", priority=0)
    normal = planner.for_task(runtime.spec, "reasoning", priority=50)
    high = planner.for_task(runtime.spec, "reasoning", priority=100)
    assert low.max_duration_seconds == 90.0
    assert normal.max_duration_seconds == 120.0
    assert high.max_duration_seconds == 150.0


def test_resource_reserve_scales_with_physical_ram_not_ram_expansion(tmp_path):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    spec = ModelSpec("qwen", model, cache_dir=tmp_path)
    hardware = FakeHardware(ram_mb=4096, total_ram_mb=12_288, storage_path=tmp_path)
    policy = ModelResourcePolicy(hardware, lambda: {
        "app_foreground": True, "screen_interactive": True, "thermal_status": "light",
    })
    decision = policy.evaluate(spec, phase="load")
    assert decision["total_ram_mb"] == 12_288
    assert decision["load_reserve_mb"] >= 983


def test_background_request_requires_explicit_matching_opt_in():
    with pytest.raises(ValueError, match="allow_background=True"):
        ResourceRequest(task_class="background")
    with pytest.raises(ValueError, match="classe background"):
        ResourceRequest(task_class="interactive", allow_background=True)

def test_admission_reports_total_ram_and_applies_adaptive_reserve(tmp_path):
    runtime, _ = make_runtime(tmp_path, ram=4096)
    decision = runtime.admission.evaluate(runtime.spec, phase="load")
    assert decision["allowed"] is True
    assert decision["total_ram_mb"] == 12288
    assert decision["load_reserve_mb"] >= 983
    runtime.close()

def test_litert_backend_reserves_final_output_tokens_and_applies_sampler_config():
    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message_async(self, _prompt):
            return iter([{"content": [{"type": "text", "text": "ok"}]}])

    class FakeEngine:
        def __init__(self):
            self.kwargs = None

        def create_conversation(self, **kwargs):
            self.kwargs = kwargs
            return FakeConversation()

    backend = LiteRTLMBackend()
    engine = FakeEngine()
    backend._engine = engine
    backend._litert_module = types.SimpleNamespace(
        ThinkingConfig=lambda **kwargs: kwargs,
        SamplerConfig=lambda **kwargs: kwargs,
    )
    request = ResourceRequest(
        task_class="interactive",
        thinking_token_budget=256,
        max_output_tokens=512,
        top_k=40,
        top_p=0.9,
        temperature=0.35,
        max_duration_seconds=5,
    )

    assert backend.generate("responda", request=request) == "ok"
    assert engine.kwargs["max_output_tokens"] == 768
    assert engine.kwargs["sampler_config"] == {
        "top_k": 40, "top_p": 0.9, "temperature": 0.35
    }


def test_android_provider_acknowledges_result_after_successful_decode():
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    calls = []
    outputs = {
        "infer": "Result: Bundle[{status=accepted}]",
        "result": (
            "Result: Bundle[{status=completed, deadline_met=true, "
            "text_b64=SGVsbG8=}]"
        ),
        "ack": "Result: Bundle[{status=acknowledged}]",
    }

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append((method, arg))
        return outputs[method]

    backend._call = fake_call
    request = ResourceRequest(task_class="interactive", max_duration_seconds=5)

    assert backend.generate("prompt", request=request) == "Hello"
    assert [method for method, _ in calls] == ["infer", "result", "ack"]
    request_id = json.loads(calls[0][1])["request_id"]
    assert calls[1][1] == request_id
    assert calls[2][1] == request_id


def test_android_provider_acknowledges_terminal_failure():
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    calls = []
    outputs = iter([
        "Result: Bundle[{status=accepted}]",
        "Result: Bundle[{status=failed, error=IllegalStateException}]",
        "Result: Bundle[{status=acknowledged}]",
    ])

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append(method)
        return next(outputs)

    backend._call = fake_call
    request = ResourceRequest(task_class="interactive", max_duration_seconds=5)

    with pytest.raises(ModelRuntimeError, match="IllegalStateException"):
        backend.generate("prompt", request=request)
    assert calls == ["infer", "result", "ack"]


def test_android_provider_does_not_acknowledge_malformed_result_payload():
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    calls = []
    outputs = iter([
        "Result: Bundle[{status=accepted}]",
        "Result: Bundle[{status=completed, deadline_met=true, text_b64=not-base64!}]",
    ])

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append(method)
        return next(outputs)

    backend._call = fake_call
    request = ResourceRequest(task_class="interactive", max_duration_seconds=5)

    with pytest.raises(ModelRuntimeError, match="invalid text encoding"):
        backend.generate("prompt", request=request)
    assert calls == ["infer", "result"]


def test_android_provider_ack_failure_does_not_discard_consumed_result():
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    calls = []
    outputs = {
        "infer": "Result: Bundle[{status=accepted}]",
        "result": (
            "Result: Bundle[{status=completed, deadline_met=true, "
            "text_b64=SGVsbG8=}]"
        ),
    }

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append(method)
        if method == "ack":
            raise ModelUnavailableError("provider temporarily unavailable")
        return outputs[method]

    backend._call = fake_call
    request = ResourceRequest(task_class="interactive", max_duration_seconds=5)

    assert backend.generate("prompt", request=request) == "Hello"
    assert calls == ["infer", "result", "ack"]


def test_android_provider_maps_cancelled_terminal_state_and_acknowledges_it():
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    calls = []
    outputs = iter([
        "Result: Bundle[{status=accepted}]",
        "Result: Bundle[{status=cancelled, request_id=req-cancelled}]",
        "Result: Bundle[{status=acknowledged}]",
    ])

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append((method, arg))
        return next(outputs)

    backend._call = fake_call
    request = ResourceRequest(task_class="interactive", max_duration_seconds=5)

    with pytest.raises(ModelInferenceCancelled, match="cancelled"):
        backend.generate("prompt", request=request)
    assert [method for method, _ in calls] == ["infer", "result", "ack"]
    request_id = json.loads(calls[0][1])["request_id"]
    assert calls[1][1] == request_id
    assert calls[2][1] == request_id


def test_android_provider_exposes_request_id_scoped_cancel_operation():
    backend = AndroidContentProviderBackend()
    calls = []

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append((method, arg))
        return "Result: Bundle[{status=cancellation_requested}]"

    backend._call = fake_call
    assert backend.cancel_request("request-exact") == "cancellation_requested"
    assert calls == [("cancel", "request-exact")]


def test_android_provider_timeout_cancels_exact_request_and_waits_for_terminal_ack(
    monkeypatch,
):
    backend = AndroidContentProviderBackend(poll_interval_seconds=0.01)
    backend._loaded = True
    calls = []
    outputs = {
        "infer": "Result: Bundle[{status=accepted}]",
        "result": [
            "Result: Bundle[{status=pending, request_id=req-timeout}]",
            "Result: Bundle[{status=cancelled, request_id=req-timeout}]",
        ],
        "cancel": "Result: Bundle[{status=cancellation_requested}]",
        "ack": "Result: Bundle[{status=acknowledged}]",
    }

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append((method, arg))
        if method == "result":
            return outputs[method].pop(0)
        return outputs[method]

    backend._call = fake_call
    monkeypatch.setattr("agent.model_runtime.uuid.uuid4", lambda: types.SimpleNamespace(hex="req-timeout"))
    clock = iter([0.0, 0.0, 31.0, 31.0, 31.0])
    monkeypatch.setattr("agent.model_runtime.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("agent.model_runtime.time.sleep", lambda _seconds: None)
    request = ResourceRequest(task_class="interactive", max_duration_seconds=0.01)

    with pytest.raises(ModelInferenceCancelled, match="wait budget expired"):
        backend.generate("prompt", request=request)
    assert [method for method, _ in calls] == ["infer", "result", "cancel", "result", "ack"]
    assert calls[2] == ("cancel", "req-timeout")
    assert calls[-1] == ("ack", "req-timeout")


def test_model_runtime_preserves_typed_backend_cancellation(tmp_path):
    class CancelledBackend(FakeBackend):
        def generate(self, prompt, *, request):
            raise ModelInferenceCancelled("cancelled by test")

    runtime, _ = make_runtime(tmp_path, backend=CancelledBackend())
    with pytest.raises(ModelInferenceCancelled, match="cancelled by test"):
        runtime.generate("prompt")
    runtime.close()



def test_android_provider_timeout_does_not_ack_when_cancel_transport_fails(monkeypatch):
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    calls = []

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append((method, arg))
        if method == "infer":
            return "Result: Bundle[{status=accepted}]"
        if method == "result":
            return "Result: Bundle[{status=pending}]"
        if method == "cancel":
            raise ModelUnavailableError("provider unavailable")
        raise AssertionError(f"unexpected method: {method}")

    backend._call = fake_call
    monkeypatch.setattr("agent.model_runtime.uuid.uuid4", lambda: types.SimpleNamespace(hex="req-lost-cancel"))
    clock = iter([0.0, 0.0, 31.0])
    monkeypatch.setattr("agent.model_runtime.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("agent.model_runtime.time.sleep", lambda _seconds: None)
    request = ResourceRequest(task_class="interactive", max_duration_seconds=0.01)

    with pytest.raises(ModelDeadlineExceeded, match="native execution state is unknown"):
        backend.generate("prompt", request=request)
    assert [method for method, _ in calls] == ["infer", "result", "cancel"]
    assert all(method != "ack" for method, _ in calls)


def test_android_provider_timeout_keeps_pending_result_unacknowledged(monkeypatch):
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    calls = []
    result_states = iter([
        "Result: Bundle[{status=pending}]",
        "Result: Bundle[{status=pending}]",
    ])

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append((method, arg))
        if method == "infer":
            return "Result: Bundle[{status=accepted}]"
        if method == "result":
            return next(result_states)
        if method == "cancel":
            return "Result: Bundle[{status=cancellation_requested}]"
        raise AssertionError(f"unexpected method: {method}")

    backend._call = fake_call
    monkeypatch.setattr("agent.model_runtime.uuid.uuid4", lambda: types.SimpleNamespace(hex="req-still-pending"))
    clock = [0.0]
    result_call_count = [0]
    original_fake_call = fake_call

    def advancing_fake_call(method, arg=None, timeout_seconds=15.0):
        if method == "result":
            result_call_count[0] += 1
            clock[0] = 31.0 if result_call_count[0] == 1 else 42.0
        return original_fake_call(method, arg, timeout_seconds)

    backend._call = advancing_fake_call
    monkeypatch.setattr("agent.model_runtime.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("agent.model_runtime.time.sleep", lambda _seconds: None)
    request = ResourceRequest(task_class="interactive", max_duration_seconds=0.01)

    with pytest.raises(ModelDeadlineExceeded, match="no terminal result arrived"):
        backend.generate("prompt", request=request)
    assert [method for method, _ in calls] == ["infer", "result", "cancel", "result"]
    assert all(method != "ack" for method, _ in calls)



def test_resource_request_validates_sampling_parameters():
    request = ResourceRequest(top_k=32, top_p=0.92, temperature=0.4)
    assert request.top_k == 32
    assert request.top_p == 0.92
    assert request.temperature == 0.4

    for kwargs in (
        {"top_k": 0},
        {"top_k": True},
        {"top_p": 1.1},
        {"top_p": float("nan")},
        {"temperature": -0.1},
        {"temperature": float("inf")},
        {"temperature": True},
        {"temperature": 2.1},
    ):
        with pytest.raises(ValueError):
            ResourceRequest(**kwargs)


def test_android_provider_payload_preserves_sampling_parameters():
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    captured = {}

    def fake_call(method, arg=None, timeout_seconds=15.0):
        if method == "infer":
            captured.update(json.loads(arg))
            return "Result: Bundle[{status=accepted}]"
        if method == "result":
            return "Result: Bundle[{status=completed, deadline_met=true, text_b64=SGk=}]"
        if method == "ack":
            return "Result: Bundle[{status=acknowledged}]"
        raise AssertionError(method)

    backend._call = fake_call
    request = ResourceRequest(
        task_class="interactive",
        max_duration_seconds=5,
        top_k=24,
        top_p=0.88,
        temperature=0.25,
    )
    assert backend.generate("prompt", request=request) == "Hi"
    assert captured["top_k"] == 24
    assert captured["top_p"] == 0.88
    assert captured["temperature"] == 0.25
    assert "duration_policy_applied" not in captured




def test_android_cancellation_terminal_poll_never_exceeds_remaining_deadline(monkeypatch):
    backend = AndroidContentProviderBackend()
    backend._loaded = True
    backend.poll_interval_seconds = 0.0
    clock = [0.0]
    recorded_timeouts = []
    result_calls = [0]

    def fake_monotonic():
        return clock[0]

    def fake_call(method, arg=None, timeout_seconds=15.0):
        if method == "infer":
            return "Result: Bundle[{status=accepted}]"
        if method == "result":
            result_calls[0] += 1
            if result_calls[0] == 1:
                # Expire the caller's original wait budget.
                clock[0] = 32.0
            else:
                recorded_timeouts.append(timeout_seconds)
                # Simulate a provider poll consuming more than the remaining
                # terminal window; the subprocess timeout must cap this call.
                clock[0] += 11.0
            return "Result: Bundle[{status=pending}]"
        raise AssertionError(f"unexpected provider method: {method}")

    monkeypatch.setattr(model_runtime_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(model_runtime_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(backend, "_call", fake_call)
    monkeypatch.setattr(
        backend, "cancel_request", lambda request_id: "cancellation_requested"
    )

    with pytest.raises(ModelDeadlineExceeded, match="no terminal result"):
        backend.generate(
            "prompt",
            request=ResourceRequest(max_duration_seconds=1.0),
        )

    assert recorded_timeouts == [10.0]



def test_resource_request_uses_qwen3_thinking_sampler_defaults():
    defaults = ResourceRequest()
    assert defaults.top_k == 20
    assert defaults.top_p == 0.95
    assert defaults.temperature == 0.6

    partial_override = ResourceRequest(temperature=0.4)
    assert partial_override.top_k == 20
    assert partial_override.top_p == 0.95
    assert partial_override.temperature == 0.4



def test_adaptive_backend_fails_closed_when_android_fallback_is_not_enabled(tmp_path):
    class FailedPrimary:
        def load(self, model_path):
            raise ModelUnavailableError("python wheel unavailable")

    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    backend = AdaptiveModelBackend(
        primary=FailedPrimary(),
        allow_android_fallback=False,
    )

    with pytest.raises(ModelUnavailableError, match="fallback Android não habilitado"):
        backend.load(model)

    assert backend.fallback is None
    assert backend.active is None



def test_android_provider_rejects_missing_or_incompatible_prompt_protocol(tmp_path):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model fixture")
    backend = AndroidContentProviderBackend()
    calls = []

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append(method)
        return (
            "Result: Bundle[{status=unloaded, prompt_protocol_version=2, "
            "prompt_protocol=legacy_text, model_sha256=unused}]"
        )

    backend._call = fake_call
    with pytest.raises(ModelUnavailableError, match="prompt protocol"):
        backend.load(model)
    assert calls == ["status"]
    assert backend._loaded is False


def test_android_provider_accepts_versioned_structured_prompt_protocol(tmp_path):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model fixture")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    backend = AndroidContentProviderBackend()
    calls = []

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append(method)
        if method == "status":
            return (
                "Result: Bundle[{status=unloaded, prompt_protocol_version=1, "
                f"prompt_protocol=mahoraga_messages_v1, model_sha256={digest}]}}"
            )
        if method == "load":
            return "Result: Bundle[{status=loaded}]"
        raise AssertionError(f"unexpected provider method: {method}")

    backend._call = fake_call
    backend.load(model)

    assert calls == ["status", "load"]
    assert backend._loaded is True


def test_load_checks_free_space_on_runtime_cache_mount_not_model_mount(tmp_path):
    model_dir = tmp_path / "model-volume"
    cache_dir = tmp_path / "runtime-cache-volume"
    model_dir.mkdir()
    cache_dir.mkdir()
    model = model_dir / "qwen.litertlm"
    model.write_bytes(b"model-fixture")

    hardware = FakeHardware(storage_path=model_dir)
    hardware.resource_snapshot = lambda: {
        "captured_at": "test",
        "memory": {"values": {
            "MemAvailable": {"mb": 8192},
            "MemTotal": {"mb": 12288},
        }},
        "storage": {
            "model_mount": {
                "path": str(model_dir),
                "free_bytes": 8192 * 1024 * 1024,
            },
            "cache_mount": {
                "path": str(cache_dir),
                "free_bytes": 32 * 1024 * 1024,
            },
        },
    }
    runtime = ModelRuntime(
        ModelSpec("qwen", model, cache_dir=cache_dir),
        FakeBackend(),
        ModelResourcePolicy(
            hardware,
            lambda: {
                "app_foreground": True,
                "screen_interactive": True,
                "thermal_status": "normal",
            },
        ),
    )

    result = runtime.load()

    assert result["loaded"] is False
    assert result["admission"]["reason"] == "insufficient_free_storage"
    assert result["admission"]["free_storage_mb"] == 32
    assert result["admission"]["required_storage_mb"] >= 256


def test_python_litert_backend_cancels_native_conversation_when_deadline_expires(
    tmp_path, monkeypatch
):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"model")
    state = {"conversations": [], "engine_closed": False, "slow_stream": True}

    class FakeConversation:
        def __init__(self, config):
            self.config = config
            self.cancelled = False
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.closed = True

        def cancel_process(self):
            self.cancelled = True

        def send_message_async(self, prompt):
            time.sleep(0.02)
            yield {"content": [{"type": "text", "text": "late"}]}

    class FakeEngine:
        def __init__(self, path, **options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            state["engine_closed"] = True

        def create_conversation(self, **config):
            conversation = FakeConversation(config)
            state["conversations"].append(conversation)
            return conversation

    fake_module = types.SimpleNamespace(
        Backend=types.SimpleNamespace(CPU=lambda: "cpu", GPU=lambda: "gpu"),
        Engine=FakeEngine,
        ThinkingConfig=lambda **kwargs: kwargs,
        SamplerConfig=lambda **kwargs: kwargs,
    )
    monkeypatch.setitem(sys.modules, "litert_lm", fake_module)

    backend = LiteRTLMBackend(cache_dir=tmp_path)
    backend.load(model)
    request = ResourceRequest(max_duration_seconds=0.001)

    with pytest.raises(ModelDeadlineExceeded):
        backend.generate("deadline test", request=request)

    assert len(state["conversations"]) == 1
    assert state["conversations"][0].cancelled is True
    assert state["conversations"][0].closed is True
    backend.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_prompt_chars": True},
        {"max_output_chars": 12.5},
        {"context_window_tokens": 4096.5},
        {"estimated_peak_ram_mb": 1024.5},
        {"runtime_overhead_mb": 768.0},
        {"expected_sha256": 123},
    ],
)
def test_model_spec_rejects_malformed_numeric_and_digest_types(tmp_path, kwargs):
    with pytest.raises(ValueError):
        ModelSpec("qwen", tmp_path / "qwen.litertlm", **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"priority": 50.5},
        {"estimated_peak_ram_mb": 1024.5},
        {"max_output_tokens": 256.5},
        {"max_duration_seconds": "30"},
        {"allow_background": 1},
    ],
)
def test_resource_request_rejects_malformed_policy_types(kwargs):
    with pytest.raises(ValueError):
        ResourceRequest(**kwargs)


@pytest.mark.parametrize("duration", [True, 0, -1, float("nan"), float("inf"), "30"])
def test_adaptive_budget_planner_rejects_invalid_requested_duration(tmp_path, duration):
    runtime, _ = make_runtime(tmp_path)
    planner = AdaptiveBudgetPlanner(runtime.admission.hardware)
    with pytest.raises(ValueError, match="requested_duration_seconds"):
        planner.for_task(
            runtime.spec,
            "interactive",
            requested_duration_seconds=duration,
        )


@pytest.mark.parametrize(
    "messages",
    [
        [
            {"role": "user", "content": "Pergunta."},
            {"role": "system", "content": "Instrução tardia."},
            {"role": "user", "content": "Outra pergunta."},
        ],
        [
            {"role": "system", "content": "Instrução."},
            {"role": "assistant", "content": "Resposta final indevida."},
        ],
    ],
)
def test_litert_structured_envelope_rejects_invalid_system_order_or_final_role(messages):
    envelope = json.dumps({
        "format": "mahoraga_messages_v1",
        "messages": messages,
    })
    with pytest.raises(ModelRuntimeError):
        LiteRTLMBackend._structured_messages(envelope)


def test_python_litert_envelope_fails_closed_for_malformed_recognized_json():
    with pytest.raises(ModelRuntimeError, match="JSON inválido"):
        LiteRTLMBackend._structured_messages(
            '{"format":"mahoraga_messages_v1","messages":['
        )


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "x"} for _ in range(33)],
        [{"role": "user", "content": "x" * 20_001}],
        [
            {"role": "user", "content": "x" * 17_000},
            {"role": "assistant", "content": "y" * 17_000},
            {"role": "user", "content": "z" * 17_000},
        ],
    ],
)
def test_python_litert_envelope_enforces_shared_message_count_and_character_limits(messages):
    envelope = json.dumps({
        "format": "mahoraga_messages_v1",
        "messages": messages,
    })
    with pytest.raises(ModelRuntimeError):
        LiteRTLMBackend._structured_messages(envelope)


def test_android_provider_requires_matching_structured_prompt_protocol_and_artifact_digest(
    tmp_path,
):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"android-model")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    backend = AndroidContentProviderBackend()
    calls = []

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append((method, arg))
        if method == "status":
            return (
                "Result: Bundle[{prompt_protocol_version=1, "
                "prompt_protocol=mahoraga_messages_v1, "
                f"model_sha256={digest}}}]"
            )
        if method == "load":
            return "Result: Bundle[{status=loaded}]"
        raise AssertionError(f"unexpected method: {method}")

    backend._call = fake_call
    backend.load(model)

    assert backend._loaded is True
    assert calls == [("status", None), ("load", "cpu")]


@pytest.mark.parametrize(
    "status",
    [
        "Result: Bundle[{prompt_protocol_version=0, prompt_protocol=mahoraga_messages_v1}]",
        "Result: Bundle[{prompt_protocol_version=1, prompt_protocol=legacy_text}]",
    ],
)
def test_android_provider_fails_closed_when_prompt_protocol_is_incompatible(
    tmp_path, status
):
    model = tmp_path / "qwen.litertlm"
    model.write_bytes(b"android-model")
    backend = AndroidContentProviderBackend()
    calls = []

    def fake_call(method, arg=None, timeout_seconds=15.0):
        calls.append(method)
        return status

    backend._call = fake_call
    with pytest.raises(ModelUnavailableError, match="protocol"):
        backend.load(model)
    assert calls == ["status"]


def _shared_prompt_fixture(name):
    fixture = (
        Path(__file__).resolve().parents[1]
        / "android-runtime"
        / "app"
        / "src"
        / "test"
        / "resources"
        / name
    )
    return fixture.read_text(encoding="utf-8")


def test_python_litert_parser_accepts_shared_kotlin_valid_prompt_fixture():
    prompt = _shared_prompt_fixture("mahoraga_messages_v1_valid.json")
    parsed = LiteRTLMBackend._structured_messages(prompt)
    assert parsed[0][0]["role"] == "system"
    assert parsed[0][1]["role"] == "user"
    assert parsed[0][2]["role"] == "assistant"
    assert parsed[1]["role"] == "user"
    assert parsed[1]["content"][0]["text"] == "Pergunta atual."


def test_python_litert_parser_rejects_shared_kotlin_invalid_order_fixture():
    prompt = _shared_prompt_fixture("mahoraga_messages_v1_invalid_system_order.json")
    with pytest.raises(ModelRuntimeError, match="system LiteRT"):
        LiteRTLMBackend._structured_messages(prompt)


def test_adaptive_backend_disables_android_fallback_by_default():
    backend = AdaptiveModelBackend()
    assert backend.fallback is None
    assert backend.active is None
