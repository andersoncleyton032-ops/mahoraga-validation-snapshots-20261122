import json
from types import SimpleNamespace

import pytest

from agent.identity_engine import IdentityEngine
from agent.store import KnowledgeStore


class AllowObservation:
    def evaluate(self, action):
        assert action == "record_observation"
        return SimpleNamespace(allowed=True, reason="")


def write_minimal_identity_profile(root):
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema": "mahoraga.identity_profile",
        "version": "1.0.0",
        "identity": {
            "name": "Mahoraga",
            "designation": "agente adaptável",
            "purpose": "preservar conhecimento e desenvolver capacidades",
        },
        "personality": {
            "behavioral_expression": "direto e criterioso",
            "traits": ["curioso"],
            "invariants": ["honestidade"],
        },
        "communication": {"behavior": ["claro"]},
        "autonomy": {
            "default_mode": "governed",
            "policy": "não executar ações sem autorização",
        },
        "self_image": {"concept": "entidade computacional integrada"},
        "continuity": {"strategy": "preservar estado e proveniência"},
        "core_principles": ["integridade"],
        "boundaries": ["não alegar consciência subjetiva"],
        "goals": [{"id": "g1", "name": "evoluir capacidades"}],
        "creative_domains": [{"id": "c1", "name": "criação"}],
    }
    (config / "identity_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False),
        encoding="utf-8",
    )


def test_identity_milestone_blocks_unverified_caller_attestation(tmp_path):
    write_minimal_identity_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, AllowObservation())

    with pytest.raises(PermissionError, match="verificador independente"):
        identity.record_milestone(
            "Marco validado",
            "Evidência append-only",
            ["ci:run-1", "commit:abc"],
            approved=True,
        )

    assert store.list_events(event_type="identity.milestone.recorded") == []


def test_identity_milestone_still_requires_explicit_caller_acknowledgement(tmp_path):
    write_minimal_identity_profile(tmp_path)
    store = KnowledgeStore(tmp_path / "identity.sqlite3")
    identity = IdentityEngine(tmp_path, store, AllowObservation())

    with pytest.raises(PermissionError, match="aprovação explícita"):
        identity.record_milestone(
            "Marco",
            "Sem confirmação",
            ["ci:run-2"],
        )
    assert store.list_events(event_type="identity.milestone.recorded") == []
