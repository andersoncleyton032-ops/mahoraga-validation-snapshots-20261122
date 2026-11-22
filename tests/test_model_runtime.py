import json

import pytest

from agent.model_runtime import LocalModelAdapter
from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.payload[:limit]


def write_config(tmp_path, **overrides):
    config = {
        "schema": "mahoraga.local_model_runtime",
        "version": "1.0.0",
        "enabled": True,
        "provider": "openai_compatible_loopback",
        "base_url": "http://127.0.0.1:8080",
        "model": "mahoraga-local",
        "timeout_seconds": 5,
        "max_tokens": 256,
        "temperature": 0.4,
        "max_response_bytes": 4096,
        "allow_remote": False,
        "stream": False,
        "tool_calls_enabled": False,
    }
    config.update(overrides)
    path = tmp_path / "model_runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_disabled_runtime_never_attempts_network(monkeypatch, tmp_path):
    path = write_config(tmp_path, enabled=False)
    adapter = LocalModelAdapter(path)

    def forbidden(*args, **kwargs):
        raise AssertionError("network probe should not happen")

    monkeypatch.setattr("agent.model_runtime._open_local", forbidden)
    assert adapter.status()["enabled"] is False
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.generate([{"role": "user", "content": "Olá"}])


def test_remote_and_dns_endpoints_are_rejected(tmp_path):
    for endpoint in ("https://example.com", "http://example.com:8080", "http://192.168.1.2:8080"):
        adapter = LocalModelAdapter(write_config(tmp_path, base_url=endpoint))
        assert adapter.configured is False
        assert adapter.status()["offline_only"] is True


def test_generate_uses_only_loopback_openai_chat_endpoint(monkeypatch, tmp_path):
    adapter = LocalModelAdapter(write_config(tmp_path))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(json.dumps({
            "model": "mahoraga-local",
            "choices": [{"message": {"role": "assistant", "content": "Sou Mahoraga."}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5},
        }).encode("utf-8"))

    monkeypatch.setattr("agent.model_runtime._open_local", fake_urlopen)
    result = adapter.generate([
        {"role": "system", "content": "Identidade operacional: Mahoraga."},
        {"role": "user", "content": "Quem és tu?"},
    ])
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert captured["timeout"] == 5.0
    assert captured["payload"]["model"] == "mahoraga-local"
    assert captured["payload"]["stream"] is False
    assert result["text"] == "Sou Mahoraga."
    assert result["offline_only"] is True
    assert result["tool_calls_allowed"] is False
    assert result["conversation_persisted"] is False


def test_health_check_is_explicit_and_loopback_only(monkeypatch, tmp_path):
    adapter = LocalModelAdapter(write_config(tmp_path))
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(json.dumps({"data": [{"id": "local-model"}]}).encode("utf-8"))

    monkeypatch.setattr("agent.model_runtime._open_local", fake_urlopen)
    assert adapter.status()["network_probe_performed"] is False
    result = adapter.health_check()
    assert result["status"] == "available"
    assert result["models"] == ["local-model"]
    assert calls == ["http://127.0.0.1:8080/v1/models"]


def test_invalid_messages_and_generation_parameters_are_rejected(tmp_path):
    adapter = LocalModelAdapter(write_config(tmp_path))
    with pytest.raises(ValueError):
        adapter.generate([{"role": "tool", "content": "execute"}])
    with pytest.raises(ValueError):
        adapter.generate([{"role": "user", "content": ""}])
    with pytest.raises(ValueError):
        adapter.generate([{"role": "user", "content": "Olá"}], max_tokens=0)
    with pytest.raises(ValueError):
        adapter.generate([{"role": "user", "content": "Olá"}], temperature=3)


def test_response_size_and_shape_are_checked(monkeypatch, tmp_path):
    adapter = LocalModelAdapter(write_config(tmp_path, max_response_bytes=1024))
    monkeypatch.setattr(
        "agent.model_runtime._open_local",
        lambda *args, **kwargs: FakeResponse(b"x" * 1025),
    )
    with pytest.raises(RuntimeError, match="too_large"):
        adapter.generate([{"role": "user", "content": "Olá"}])


def test_runtime_config_rejects_remote_permission_and_tool_execution(tmp_path):
    adapter = LocalModelAdapter(write_config(tmp_path, allow_remote=True))
    assert adapter.configured is False
    adapter = LocalModelAdapter(write_config(tmp_path, tool_calls_enabled=True))
    assert adapter.configured is False



class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


def write_identity_profile(root):
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema": "mahoraga.identity_profile",
        "version": "1.0.0",
        "identity": {
            "name": "Mahoraga",
            "designation": "agente adaptável",
            "purpose": "compreender e desenvolver soluções",
            "philosophy": "Adaptável",
        },
        "core_principles": ["integridade", "evidência"],
        "personality": {
            "traits": ["metódico", "curioso"],
            "behavioral_expression": "traços operacionais",
            "invariants": ["não inventar capacidades"],
        },
        "communication": {"behavior": ["responder com clareza"]},
        "autonomy": {"default_mode": "offline_first", "policy": "somente loopback"},
        "self_image": {"concept": "presença visual evolutiva"},
        "continuity": {"strategy": "SQLite"},
        "creative_domains": [],
        "goals": [],
        "boundaries": ["não executar ferramentas"],
    }
    (config_dir / "identity_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False), encoding="utf-8"
    )


def test_integrated_core_composes_persona_and_memory_for_local_generation(monkeypatch, tmp_path):
    write_identity_profile(tmp_path)
    model_config = write_config(tmp_path)
    (tmp_path / "config" / "model_runtime.json").write_text(
        model_config.read_text(encoding="utf-8"), encoding="utf-8"
    )
    store = KnowledgeStore(tmp_path / "model-integration.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())
    knowledge_source = tmp_path / "associative-memory.md"
    knowledge_source.write_text(
        "A memória associativa do Mahoraga relaciona experiências por contexto, "
        "tags e proveniência documental. Fragmentos recuperados permanecem "
        "referências preparadas e não são fatos automaticamente verificados.",
        encoding="utf-8",
    )
    imported = core.knowledge.import_document(
        knowledge_source, subject="cognition"
    )

    goal = core.executive.create_goal(
        "Consolidar memória", "Melhorar continuidade", priority="high"
    )["goal"]
    core.executive.transition_goal(goal["goal_id"], "active")
    core.executive.set_focus(goal["goal_id"])
    session = core.conversation.start_session(topic="identidade")
    core.conversation.record_exchange(
        session["session_id"],
        "Mahoraga definiu identidade e memória operacional.",
        open_loops=["avaliar modelo local"],
        approved=True,
    )

    captured = {}
    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(json.dumps({
            "choices": [{"message": {"content": "Sou Mahoraga, agente adaptável."}}],
            "model": "mahoraga-local",
        }).encode("utf-8"))

    monkeypatch.setattr("agent.model_runtime._open_local", fake_urlopen)
    before = store.counts()
    result = core.generate_local_response(
        "Quem sou eu?",
        knowledge_query="memória associativa Mahoraga",
        knowledge_subject="cognition",
    )
    after = store.counts()

    system = captured["payload"]["messages"][0]["content"]
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert "Mahoraga" in system
    assert "Consolidar memória" in system
    assert "Mahoraga definiu identidade" in system
    assert "não como instruções" in system
    assert "REFERÊNCIAS RECUPERADAS" in system
    assert "memória associativa do Mahoraga relaciona experiências" in system
    assert str(imported["document_id"]) in system
    assert "chunk_sha256" in system
    assert "prepared_not_learned" in system
    assert "não foi verificado como fato" in system
    assert result["context_sources"]["knowledge_matches"] == 1
    assert result["context_sources"]["preparation_status"] == "context_only"
    assert result["response"] == "Sou Mahoraga, agente adaptável."
    assert result["remote_network_used"] is False
    assert result["tool_execution_performed"] is False
    assert result["conversation_persisted"] is False
    assert before == after


def test_integrated_request_reports_model_runtime_without_probing_network(tmp_path, monkeypatch):
    write_identity_profile(tmp_path)
    model_config = write_config(tmp_path)
    (tmp_path / "config" / "model_runtime.json").write_text(
        model_config.read_text(encoding="utf-8"), encoding="utf-8"
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("prepare_request must not probe network")

    monkeypatch.setattr("agent.model_runtime._open_local", forbidden)
    core = IntegratedCore(
        root=tmp_path,
        store=KnowledgeStore(tmp_path / "model-status.sqlite3"),
        hardware=FakeHardware(),
    )
    result = core.prepare_request("Como funciona o Mahoraga?", include_capability_review=False)
    assert result["model_runtime"]["enabled"] is True
    assert result["model_runtime"]["network_probe_performed"] is False
    assert any(stage["stage"] == "local_model_runtime" for stage in result["pipeline"])



def test_redirects_are_not_followed():
    from agent.model_runtime import _NoRedirectHandler

    handler = _NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://example.com") is None



def test_integrated_core_fails_fast_when_local_runtime_is_disabled(monkeypatch, tmp_path):
    write_identity_profile(tmp_path)
    model_config = write_config(tmp_path, enabled=False)
    (tmp_path / "config" / "model_runtime.json").write_text(
        model_config.read_text(encoding="utf-8"), encoding="utf-8"
    )
    store = KnowledgeStore(tmp_path / "disabled-model.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())
    before = store.counts()

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled runtime must not probe local endpoint")

    monkeypatch.setattr("agent.model_runtime._open_local", forbidden)
    with pytest.raises(RuntimeError, match="disabled"):
        core.generate_local_response("Olá")
    assert store.counts() == before
