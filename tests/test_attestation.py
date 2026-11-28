from __future__ import annotations

import pytest

from agent.attestation import attestation_request_id


SUBJECT = "a" * 64


def test_request_id_is_stable_for_equivalent_object_key_order():
    left = {"approved": True, "claims": {"b": 2, "a": 1}}
    right = {"claims": {"a": 1, "b": 2}, "approved": True}
    assert attestation_request_id("adaptive.promote", left, SUBJECT) == (
        attestation_request_id("adaptive.promote", right, SUBJECT)
    )


@pytest.mark.parametrize(
    ("action", "attestation", "subject"),
    [
        ("identity.milestone", {"approved": True}, SUBJECT),
        ("adaptive.promote", {"approved": False}, SUBJECT),
        ("adaptive.promote", {"approved": True}, "b" * 64),
    ],
)
def test_request_id_is_bound_to_action_subject_and_token(action, attestation, subject):
    baseline = attestation_request_id("adaptive.promote", {"approved": True}, SUBJECT)
    assert attestation_request_id(action, attestation, subject) != baseline


def test_request_id_is_opaque_and_has_sha256_shape():
    token = {"opaque_secret": "do-not-persist"}
    result = attestation_request_id("adaptive.promote", token, SUBJECT)
    assert len(result) == 64
    assert all(char in "0123456789abcdef" for char in result)
    assert "do-not-persist" not in result


@pytest.mark.parametrize(
    ("action", "attestation", "subject"),
    [
        (" ", {"ok": True}, SUBJECT),
        ("x" * 161, {"ok": True}, SUBJECT),
        ("action", {}, SUBJECT),
        ("action", "", SUBJECT),
        ("action", [], SUBJECT),
        ("action", {"ok": True}, "A" * 64),
        ("action", {"ok": True}, "f" * 63),
        ("action", {"ok": True}, None),
    ],
)
def test_request_id_rejects_invalid_top_level_inputs(action, attestation, subject):
    with pytest.raises(PermissionError):
        attestation_request_id(action, attestation, subject)


def test_request_id_rejects_non_string_object_keys():
    with pytest.raises(PermissionError, match="JSON válido"):
        attestation_request_id("action", {1: "value"}, SUBJECT)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_request_id_rejects_non_finite_numbers(value):
    with pytest.raises(PermissionError, match="JSON válido"):
        attestation_request_id("action", {"value": value}, SUBJECT)


def test_request_id_rejects_non_json_nested_types():
    with pytest.raises(PermissionError, match="JSON válido"):
        attestation_request_id("action", {"value": (1, 2)}, SUBJECT)


def test_request_id_rejects_excessive_nesting():
    value = "leaf"
    for _ in range(14):
        value = [value]
    with pytest.raises(PermissionError, match="JSON válido"):
        attestation_request_id("action", {"nested": value}, SUBJECT)


def test_request_id_rejects_payload_larger_than_8192_utf8_bytes():
    with pytest.raises(PermissionError, match="limite de tamanho"):
        attestation_request_id("action", {"value": "x" * 8193}, SUBJECT)


def test_request_id_accepts_opaque_string_attestations():
    first = attestation_request_id("action", "opaque-token", SUBJECT)
    second = attestation_request_id("action", "opaque-token", SUBJECT)
    assert first == second
