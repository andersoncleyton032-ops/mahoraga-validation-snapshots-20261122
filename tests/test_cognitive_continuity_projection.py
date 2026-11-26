from __future__ import annotations

import json

import pytest

from agent.cognitive_fabric import (
    CognitiveFabric,
    CognitiveFabricError,
    SignalDraft,
)


def make_workspace():
    fabric = CognitiveFabric()
    fabric.configure_connectome(
        component_ids=["core", "language"],
        verified_relationships={},
    )
    workspace = fabric.new_workspace(metadata={"request_characters": 42})
    workspace.put(
        "private.artifact",
        {"raw_document": "DO_NOT_PERSIST_ARTIFACT_VALUE"},
        source="core",
        epistemic_state="working_context",
    )
    fabric.publish(
        workspace,
        SignalDraft(
            topic="request.received",
            source="core",
            target="language",
            payload={"raw_text": "DO_NOT_PERSIST_SIGNAL_PAYLOAD"},
            evidence_refs=("DO_NOT_PERSIST_EVIDENCE_REF",),
        ),
    )
    workspace.record_stage(
        "language.parse",
        "language",
        status="completed",
        duration_ms=12.34567,
    )
    return workspace


def test_continuity_record_is_bounded_redacted_and_detached():
    workspace = make_workspace()
    record = workspace.continuity_record(
        "completed",
        completed_at="2026-11-26T03:00:00+00:00",
    )
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)

    assert record["schema"] == "mahoraga.cognitive_continuity_record"
    assert record["schema_version"] == 1
    assert record["outcome"] == "completed"
    assert record["cycle"]["correlation_id"] == workspace.correlation_id
    assert record["cycle"]["signal_count"] == 1
    assert record["cycle"]["artifact_count"] == 1
    assert record["cycle"]["stage_count"] == 1
    assert record["focus"]["topics_observed"] == ["request.received"]
    assert record["focus"]["participating_components"] == ["core", "language"]
    assert record["stage_measurements"][0]["duration_ms"] == 12.346
    assert record["artifacts"][0]["size_bytes"] > 0
    assert record["redaction"] == {
        "raw_request_text_included": False,
        "signal_payloads_included": False,
        "evidence_refs_included": False,
        "artifact_values_included": False,
        "model_response_included": False,
    }
    for secret in (
        "DO_NOT_PERSIST_ARTIFACT_VALUE",
        "DO_NOT_PERSIST_SIGNAL_PAYLOAD",
        "DO_NOT_PERSIST_EVIDENCE_REF",
        "raw_document",
        "raw_text",
    ):
        assert secret not in serialized

    record["focus"]["topics_observed"].append("forged.topic")
    assert workspace.operational_perspective()["focus"]["topics_observed"] == [
        "request.received"
    ]


@pytest.mark.parametrize("outcome", ["completed", "deferred", "failed", "cancelled"])
def test_continuity_record_accepts_only_terminal_outcomes(outcome):
    record = make_workspace().continuity_record(
        outcome,
        completed_at="2026-11-26T03:00:00Z",
    )
    assert record["outcome"] == outcome
    assert record["subjective_experience_status"] == "unknown_not_inferred"
    assert record["causal_attribution"] == "not_established"


@pytest.mark.parametrize("outcome", ["running", "success", "", None, [], {}])
def test_continuity_record_rejects_non_terminal_or_untyped_outcomes(outcome):
    with pytest.raises(CognitiveFabricError, match="outcome"):
        make_workspace().continuity_record(outcome)


@pytest.mark.parametrize("timestamp", ["", "not-a-time", "2026-11-26T03:00:00"])
def test_continuity_record_requires_timezone_aware_completion_time(timestamp):
    with pytest.raises(CognitiveFabricError, match="timestamp|fuso"):
        make_workspace().continuity_record("completed", completed_at=timestamp)


def test_continuity_record_rejects_unbounded_or_freeform_stage_status():
    workspace = make_workspace()
    workspace.record_stage(
        "sensitive.stage",
        "core",
        status="raw private status text",
        duration_ms=1,
    )
    with pytest.raises(CognitiveFabricError, match="stage_status"):
        workspace.continuity_record("failed")


def test_continuity_record_does_not_claim_calibrated_confidence():
    workspace = make_workspace()
    record = workspace.continuity_record("deferred")
    assert record["epistemic_summary"]["calibration_claim"] is False
    assert record["subjective_experience_status"] == "unknown_not_inferred"
