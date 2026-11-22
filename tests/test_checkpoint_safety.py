from __future__ import annotations

import io

import numpy as np
import pytest

from agent.checkpoint_safety import CheckpointPreflightError, preflight_npz


def _valid_checkpoint() -> io.BytesIO:
    stream = io.BytesIO()
    np.savez(
        stream,
        weights=np.zeros((2, 3), dtype=np.float32),
        metadata=np.frombuffer(b'{"format_version":1}', dtype=np.uint8),
    )
    stream.seek(0)
    return stream


def test_preflight_accepts_numpy_generated_npz_with_eocd():
    stream = _valid_checkpoint()
    preflight_npz(stream, {"weights": ((2, 3), np.dtype(np.float32))})
    assert stream.tell() == 0


def test_preflight_rejects_npz_without_eocd_signature():
    stream = _valid_checkpoint()
    payload = stream.getvalue().replace(b"PK\x05\x06", b"XX\x05\x06", 1)
    assert payload != stream.getvalue()
    corrupted = io.BytesIO(payload)
    with pytest.raises(CheckpointPreflightError, match="EOCD"):
        preflight_npz(corrupted, {"weights": ((2, 3), np.dtype(np.float32))})
