"""Shared cooperative cancellation primitives for bounded local operations."""
from __future__ import annotations

from threading import RLock


class OperationCancelled(RuntimeError):
    """A cooperative operation was cancelled before committing its result."""


class CancellationToken:
    """Thread-safe, request-scoped cancellation and commit gate.

    The request owner creates the token before queue admission. Cancellation and
    artifact commitment are mutually exclusive transitions under one lock.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._cancelled = False
        self._committed = False

    def cancel(self) -> bool:
        """Request cancellation; return False if already cancelled or committed."""
        with self._lock:
            if self._cancelled or self._committed:
                return False
            self._cancelled = True
            return True

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def is_committed(self) -> bool:
        with self._lock:
            return self._committed

    def begin_commit(self) -> bool:
        """Atomically claim the irreversible artifact-commit phase."""
        with self._lock:
            if self._committed or self.is_cancelled():
                return False
            self._committed = True
            return True

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise OperationCancelled("operation_cancelled")
