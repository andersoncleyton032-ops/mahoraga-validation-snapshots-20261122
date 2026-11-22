"""Low-overhead local telemetry backed by the knowledge store.

OpenTelemetry is intentionally not a hard dependency in this Android-first
stage. This adapter keeps structured events and can later export them through
OpenTelemetry without changing module APIs.
"""
from __future__ import annotations
from contextlib import contextmanager
from time import perf_counter
from .memory import get_store


@contextmanager
def operation(name: str, attributes: dict | None = None):
    started = perf_counter()
    status = "ok"
    error = None
    try:
        yield
    except Exception as exc:
        status = "error"
        error = {"type": type(exc).__name__, "message": str(exc)[:500]}
        raise
    finally:
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        get_store().record_event("operation.trace", {"name": name, "status": status,
            "elapsed_ms": elapsed_ms, "attributes": attributes or {}, "error": error},
            severity="error" if error else "info")
