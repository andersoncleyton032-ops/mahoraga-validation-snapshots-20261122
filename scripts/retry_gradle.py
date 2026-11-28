"""Retry Gradle only for transient repository/network failures."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import TextIO

TRANSIENT_FAILURE_MARKERS = (
    "too many requests",
    "status code 429",
    "status code 500",
    "status code 502",
    "status code 503",
    "status code 504",
    "connection reset",
    "connection timed out",
    "read timed out",
    "temporary failure in name resolution",
    "unknownhostexception",
)


def run_gradle_with_retry(
    arguments: Sequence[str],
    *,
    attempts: int = 3,
    base_delay_seconds: int = 15,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
) -> int:
    """Run Gradle, retrying only recognizable transient network/rate-limit errors."""
    if not arguments:
        raise ValueError("At least one Gradle argument/task is required.")
    if attempts < 1:
        raise ValueError("attempts must be at least 1.")
    if base_delay_seconds < 0:
        raise ValueError("base_delay_seconds must not be negative.")

    stdout = output_stream or sys.stdout
    stderr = error_stream or sys.stderr

    for attempt in range(1, attempts + 1):
        result = run(
            ["gradle", *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout:
            stdout.write(result.stdout)
            stdout.flush()
        if result.stderr:
            stderr.write(result.stderr)
            stderr.flush()

        if result.returncode == 0:
            return 0

        combined_output = f"{result.stdout}\n{result.stderr}".casefold()
        transient = any(
            marker in combined_output for marker in TRANSIENT_FAILURE_MARKERS
        )
        if not transient or attempt == attempts:
            return result.returncode

        delay = base_delay_seconds * attempt
        print(
            f"Transient Gradle repository/network failure; "
            f"retry {attempt + 1}/{attempts} in {delay}s.",
            file=stderr,
        )
        sleep(delay)

    return 1


def main(arguments: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if not args:
        print(
            "Usage: python3 scripts/retry_gradle.py <gradle arguments and tasks>",
            file=sys.stderr,
        )
        return 2
    return run_gradle_with_retry(args)


if __name__ == "__main__":
    raise SystemExit(main())
