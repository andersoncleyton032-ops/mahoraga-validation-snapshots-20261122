"""Shared helpers for bounded, retry-safe attestation request identity."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def attestation_request_id(action: str, attestation: Any, subject_sha256: str) -> str:
    """Return a stable opaque key bound to action, subject and token contents.

    Raw attestation material must never be persisted. The key is safe to use as
    an idempotency identifier with a verifier that supports retry-safe consume.
    """
    if not isinstance(action, str) or not action.strip() or len(action) > 160:
        raise PermissionError("Atestação de aprovação possui formato inválido.")
    if (
        not isinstance(subject_sha256, str)
        or len(subject_sha256) != 64
        or any(char not in "0123456789abcdef" for char in subject_sha256)
    ):
        raise PermissionError("Atestação de aprovação possui formato inválido.")
    if not isinstance(attestation, (dict, str)) or not attestation:
        raise PermissionError("Atestação de aprovação possui formato inválido.")

    def validate_json(value: Any, depth: int = 0) -> None:
        if depth > 12:
            raise ValueError("attestation nesting limit exceeded")
        if value is None or isinstance(value, (str, bool, int)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("non-finite attestation number")
            return
        if isinstance(value, list):
            for item in value:
                validate_json(item, depth + 1)
            return
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("attestation object keys must be strings")
            for item in value.values():
                validate_json(item, depth + 1)
            return
        raise ValueError("unsupported attestation value")

    try:
        validate_json(attestation)
        canonical = json.dumps(
            attestation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        encoded = canonical.encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise PermissionError("Atestação de aprovação não é JSON válido.") from exc
    if len(encoded) > 8_192:
        raise PermissionError("Atestação de aprovação excede o limite de tamanho.")

    token_sha256 = hashlib.sha256(encoded).hexdigest()
    material = action + ":" + subject_sha256 + ":" + token_sha256
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
