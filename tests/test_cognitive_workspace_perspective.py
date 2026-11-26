import json

from agent.cognitive_fabric import CognitiveFabric, SignalDraft


def test_operational_perspective_unifies_cycle_without_exposing_payloads():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["input", "language", "identity"],
        verified_relationships={},
    )
    workspace = fabric.new_workspace(metadata={"kind": "perspective_test"})
    workspace.put(
        "request_context",
        {"message": "PRIVATE REQUEST TEXT"},
        source="input",
        epistemic_state="user_input",
    )
    workspace.put(
        "identity_context",
        {"name": "Mahoraga"},
        source="identity",
        epistemic_state="identity_context",
    )
    workspace.record_stage(
        "language_understanding",
        "language",
        status="completed",
        duration_ms=2.5,
    )
    fabric.publish(
        workspace,
        SignalDraft(
            topic="request.received",
            source="input",
            target="language",
            payload={"message": "PRIVATE SIGNAL PAYLOAD"},
            epistemic_state="user_input",
            confidence=0.95,
            evidence_refs=["event:request-1"],
        ),
    )

    perspective = workspace.operational_perspective()
    serialized = json.dumps(perspective, ensure_ascii=False)

    assert perspective["schema"] == "mahoraga.operational_perspective"
    assert perspective["perspective_type"] == "request_scoped_cognitive_workspace"
    assert perspective["subjective_experience_status"] == "unknown_not_inferred"
    assert perspective["causal_attribution"] == "not_established"
    assert perspective["cycle"]["signal_count"] == 1
    assert perspective["cycle"]["artifact_count"] == 2
    assert perspective["cycle"]["stage_count"] == 1
    assert perspective["focus"]["last_signal_topic"] == "request.received"
    assert perspective["focus"]["participating_components"] == ["input", "language"]
    assert perspective["signal_chain"][0]["confidence_reported"] == 0.95
    assert perspective["signal_chain"][0]["evidence_ref_count"] == 1
    assert "event:request-1" not in serialized
    assert perspective["epistemic_summary"]["counts_by_state"] == {"user_input": 1}
    assert perspective["artifacts"][0]["artifact_key"] == "identity_context"
    assert "value" not in perspective["artifacts"][0]
    assert "PRIVATE REQUEST TEXT" not in serialized
    assert "PRIVATE SIGNAL PAYLOAD" not in serialized
    assert perspective["redaction"] == {
        "artifact_values_included": False,
        "signal_payloads_included": False,
        "raw_request_text_included": False,
    }


def test_operational_perspective_is_repeatable_and_detached_from_workspace():
    fabric = CognitiveFabric()
    fabric.configure_connectome(component_ids=["a", "b"], verified_relationships={})
    workspace = fabric.new_workspace()
    workspace.put("safe", {"ok": True}, source="a")
    fabric.publish(
        workspace,
        SignalDraft(topic="a.ready", source="a", target="b", payload={"ok": True}),
    )

    first = workspace.operational_perspective()
    second = workspace.operational_perspective()
    assert first == second

    first["focus"]["topics_observed"].append("tampered")
    first["artifacts"][0]["source"] = "tampered"
    assert workspace.operational_perspective() == second


def test_empty_workspace_has_an_explicit_empty_focus():
    fabric = CognitiveFabric()
    fabric.configure_connectome(component_ids=["core"], verified_relationships={})
    workspace = fabric.new_workspace()

    perspective = workspace.operational_perspective()

    assert perspective["focus"]["last_signal_topic"] is None
    assert perspective["focus"]["topics_observed"] == []
    assert perspective["focus"]["participating_components"] == []
    assert perspective["signal_chain"] == []
    assert perspective["artifacts"] == []
    assert perspective["stage_measurements"] == []
    assert perspective["epistemic_summary"]["reported_confidence_mean"] is None
