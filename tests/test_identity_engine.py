import json

import pytest

from agent.dharma import Dharma
from agent.identity_engine import IdentityEngine
from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore


def write_profile(root):
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema": "mahoraga.identity_profile",
        "version": "1.0.0",
        "identity": {
            "name": "Mahoraga",
            "designation": "agente adaptável",
            "purpose": "preservar conhecimento e desenvolver capacidades",
            "philosophy": "Adaptável",
        },
        "core_principles": ["integridade", "adaptação"],
        "personality": {
            "traits": ["curioso", "metódico"],
            "behavioral_expression": "traços operacionais",
            "invariants": ["não inventar evidências"],
        },
        "communication": {"behavior": ["ser claro"]},
        "autonomy": {"default_mode": "offline_first", "policy": "Dharma"},
        "self_image": {"concept": "identidade visual evolutiva"},
        "continuity": {"strategy": "SQLite persistente"},
        "creative_domains": [{"id": "creative.3d", "name": "3D", "maturity": "planned"}],
        "goals": [{"id": "goal.cognition", "name": "cognição"}],
        "boundaries": ["não declarar estados subjetivos"],
    }
    path = config / "identity_profile.json"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    return path


def test_identity_profile_loads_and_is_model_independent(tmp_path):
    write_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, Dharma(tmp_path))

    status = identity.status()
    context = identity.build_persona_context()
    image = identity.build_self_image()

    assert status["profile_available"] is True
    assert context["status"] == "ready"
    assert context["offline_compatible"] is True
    assert context["model_independent"] is True
    assert "Mahoraga" in context["context"]
    assert "\n" in context["context"]
    assert image["name"] == "Mahoraga"
    assert image["visual_identity"]["concept"] == "identidade visual evolutiva"


def test_read_only_identity_build_does_not_write_events_or_memories(tmp_path):
    write_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, Dharma(tmp_path))
    before = store.counts()
    identity.build_persona_context()
    identity.build_self_image()
    after = store.counts()
    assert before == after


def test_missing_profile_is_reported_not_silently_invented(tmp_path):
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, Dharma(tmp_path))
    assert identity.status()["profile_available"] is False
    assert identity.build_persona_context()["status"] == "unavailable"


def test_invalid_profile_is_rejected(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "identity_profile.json").write_text('{"schema":"wrong"}', encoding="utf-8")
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, Dharma(tmp_path))
    assert identity.status()["profile_available"] is False


def test_identity_milestone_requires_explicit_approval(tmp_path):
    write_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, Dharma(tmp_path))
    with pytest.raises(PermissionError):
        identity.record_milestone("Marco", "Teste", ["ci:123"])
    assert not store.list_events(event_type="identity.milestone.recorded")


def test_approved_identity_milestone_is_append_only_and_evidence_linked(tmp_path):
    write_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, Dharma(tmp_path))
    result = identity.record_milestone(
        "Marco validado", "Perfil integrado", ["ci:123", "commit:abc"],
        approved=True,
    )
    assert result["status"] == "recorded"
    assert result["automatic_identity_mutation"] is False
    events = store.list_events(event_type="identity.milestone.recorded")
    assert len(events) == 1
    assert events[0]["payload"]["evidence"] == ["ci:123", "commit:abc"]


def test_persona_context_is_bounded_and_rejects_invalid_limits(tmp_path):
    write_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, Dharma(tmp_path))
    context = identity.build_persona_context(max_chars=512)
    assert context["context_chars"] <= 512
    with pytest.raises(ValueError):
        identity.build_persona_context(max_chars=100)



class FakeHardware:
    def snapshot(self):
        return {
            "android": {"model": "test-device"},
            "available_tools": {"python": "/usr/bin/python"},
        }


def test_integrated_core_shares_identity_and_exposes_persona_context(tmp_path):
    write_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "integrated-identity.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())

    assert core.identity is core.introspection.identity
    assert core.identity.store is core.store
    assert core.identity.dharma is core.dharma

    result = core.prepare_request(
        "quero estudar memória episódica",
        include_capability_review=False,
    )
    assert result["identity"]["profile_available"] is True
    assert result["persona_context"]["status"] == "ready"
    assert result["persona_context"]["model_independent"] is True
    assert result["side_effects"]["memory_modified"] is False

    self_model = core.introspection.build_self_model(persist=False)
    assert self_model["identity_profile"]["identity"]["name"] == "Mahoraga"
    assert self_model["self_image"]["status"] == "available"



def test_executive_state_is_shared_with_introspection_and_pipeline(tmp_path):
    write_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "executive-integration.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())

    assert core.executive is core.cognitive.executive
    assert core.executive.store is core.store
    assert core.introspection.executive is core.executive

    goal = core.executive.create_goal(
        "Evoluir compreensão contextual",
        "Desenvolver memória de trabalho e acompanhamento de objetivos",
        priority="critical",
    )["goal"]
    core.executive.transition_goal(goal["goal_id"], "active")
    core.executive.set_focus(goal["goal_id"])

    prepared = core.prepare_request(
        "quero estudar compreensão contextual",
        include_capability_review=False,
    )
    assert prepared["executive"]["focus_goal_id"] == goal["goal_id"]
    assert prepared["working_memory_context"]["status"] == "ready"
    self_model = core.introspection.build_self_model(persist=False)
    assert self_model["executive_state"]["focus_goal_id"] == goal["goal_id"]
