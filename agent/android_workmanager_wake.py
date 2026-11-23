"""Fixed, no-network Android WorkManager wake adapter for Termux.

This adapter can only broadcast a request to the Mahoraga bridge app. It is
not a generic Android command runner and never invokes a shell.
"""
from __future__ import annotations

import subprocess
from typing import Callable, Any


class AndroidWorkManagerWakeAdapter:
    ACTION = "com.mahoraga.runtime.ENQUEUE_BACKGROUND_WORK"
    COMPONENT = "com.mahoraga.runtime/.WakeRequestReceiver"
    AM_PATH = "/system/bin/am"
    MIN_DELAY_SECONDS = 60
    MAX_DELAY_SECONDS = 3600
    TIMEOUT_SECONDS = 5
    ACCEPTED_RESULT = "Broadcast completed: result=1"

    def __init__(self, command_runner: Callable[..., Any] | None = None):
        self._command_runner = command_runner or subprocess.run

    @classmethod
    def valid_delay(cls, delay_seconds: int) -> bool:
        return (
            isinstance(delay_seconds, int)
            and not isinstance(delay_seconds, bool)
            and cls.MIN_DELAY_SECONDS <= delay_seconds <= cls.MAX_DELAY_SECONDS
        )

    def schedule_next(self, *, delay_seconds: int) -> bool:
        """Request one fixed explicit broadcast; require receiver enqueue acknowledgement."""
        if not self.valid_delay(delay_seconds):
            return False
        command = [
            self.AM_PATH,
            "broadcast",
            "-n",
            self.COMPONENT,
            "-a",
            self.ACTION,
            "--ei",
            "delay_seconds",
            str(delay_seconds),
        ]
        try:
            result = self._command_runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        stdout = getattr(result, "stdout", "")
        return (
            type(getattr(result, "returncode", None)) is int
            and result.returncode == 0
            and isinstance(stdout, str)
            and self.ACCEPTED_RESULT in stdout
        )
