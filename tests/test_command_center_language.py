from types import SimpleNamespace

from agent.command_center import CommandCenter


class FakeLanguage:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def classify(self, text):
        self.calls.append(text)
        return self.result


class FakeCognitive:
    def __init__(self):
        self.observations = []

    def record_observation(self, **kwargs):
        self.observations.append(kwargs)


def make_center(result):
    language = FakeLanguage(result)
    core = SimpleNamespace(
        language=language,
        cognitive=FakeCognitive(),
    )
    return CommandCenter(core), language, core


def test_exact_command_has_priority():
    center, language, _ = make_center({
        "recognized": True, "intent": "blender.inspect",
        "confidence": 1, "margin": 1
    })
    result = center.interpret("status")
    assert result["intent"] == "status"
    assert result["method"] == "exact"
    assert language.calls == []


def test_neural_status():
    center, _, _ = make_center({
        "recognized": True, "intent": "status",
        "confidence": 0.95, "margin": 0.8
    })
    result = center.interpret("como está o sistema agora?")
    assert result["recognized"]
    assert result["intent"] == "status"
    assert result["decision"] == "recognize"


def test_neural_inspection():
    center, _, _ = make_center({
        "recognized": True, "intent": "blender.inspect",
        "confidence": 0.9, "margin": 0.7
    })
    result = center.interpret("quero analisar a cena")
    assert result["recognized"]
    assert result["intent"] == "blender.inspect"


def test_model_cannot_authorize_temple_creation():
    center, _, _ = make_center({
        "recognized": True, "intent": "blender.create_temple",
        "confidence": 0.99, "margin": 0.95
    })
    result = center.interpret("crie alguma coisa")
    assert not result["recognized"]
    assert result["intent"] == "unknown"


def test_unrecognized_text():
    center, _, _ = make_center({"recognized": False})
    result = center.interpret("texto desconhecido")
    assert not result["recognized"]
    assert result["intent"] == "unknown"
    assert result["decision"] == "abstain"


def test_nan_confidence_is_rejected():
    center, _, _ = make_center({
        "recognized": True, "intent": "status",
        "confidence": float("nan"), "margin": 0.8
    })
    result = center.interpret("como está?")
    assert not result["recognized"]


def test_deferred_intention_never_submits_a_task():
    center, _, core = make_center({
        "recognized": False,
        "decision": "defer",
        "intent": "blender.inspect",
        "reason": "future_or_conditional_intention",
    })
    result = center.execute("Amanhã analise a cena.")

    assert result["status"] == "deferred"
    assert result["intent"] == "blender.inspect"
    assert not hasattr(core, "blender_bridge")


def test_ambiguous_intention_requires_clarification():
    center, _, core = make_center({
        "recognized": False,
        "decision": "clarify",
        "intent": None,
        "reason": "ambiguous_reference",
    })
    result = center.execute("Talvez olhe isso.")

    assert result["status"] == "clarification_required"
    assert result["intent"] == "unknown"
    assert not hasattr(core, "blender_bridge")


def test_prepare_routes_through_shared_cognitive_pipeline_without_dispatch():
    calls = []

    def prepare_request(command, **kwargs):
        calls.append((command, kwargs))
        return {
            "schema": "mahoraga.request_preparation",
            "plan": {"status": "context_only", "execution_performed": False},
            "side_effects": {
                "memory_modified": False,
                "learning_persisted": False,
                "neural_training_performed": False,
                "tools_executed": False,
                "external_actions_performed": False,
            },
        }

    language = FakeLanguage({"recognized": False, "decision": "abstain"})
    core = SimpleNamespace(
        language=language,
        cognitive=FakeCognitive(),
        prepare_request=prepare_request,
    )
    center = CommandCenter(core)

    result = center.prepare(
        "Explique o histórico de experiências.",
        knowledge_query="experiências",
        include_experience_review=True,
    )

    assert result["schema"] == "mahoraga.request_preparation"
    assert result["command_center"] == {
        "mode": "preparation_only",
        "dispatch_performed": False,
        "tool_execution_performed": False,
    }
    assert len(calls) == 1
    assert calls[0][0] == "Explique o histórico de experiências."
    assert calls[0][1]["include_experience_review"] is True
    assert calls[0][1]["include_capability_review"] is True
    assert language.calls == []
    assert core.cognitive.observations == []


def test_prepare_rejects_empty_input_and_handles_missing_pipeline():
    center, _, _ = make_center({"recognized": False})
    assert center.prepare(" ")["status"] == "rejected"

    core = SimpleNamespace(language=FakeLanguage({}), cognitive=FakeCognitive())
    result = CommandCenter(core).prepare("Consulte meu contexto.")
    assert result["status"] == "unavailable"
    assert result["execution_performed"] is False
