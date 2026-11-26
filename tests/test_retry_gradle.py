from __future__ import annotations

import subprocess
from io import StringIO

import pytest

from scripts.retry_gradle import run_gradle_with_retry


def completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["gradle"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_retries_maven_central_429_then_succeeds():
    results = iter([
        completed(1, stderr="Received status code 429: Too Many Requests"),
        completed(0, stdout="BUILD SUCCESSFUL"),
    ])
    calls = []
    sleeps = []
    output = StringIO()
    errors = StringIO()

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return next(results)

    status = run_gradle_with_retry(
        [":app:testDebugUnitTest"],
        attempts=3,
        base_delay_seconds=5,
        run=fake_run,
        sleep=sleeps.append,
        output_stream=output,
        error_stream=errors,
    )

    assert status == 0
    assert len(calls) == 2
    assert sleeps == [5]
    assert "BUILD SUCCESSFUL" in output.getvalue()
    assert "retry 2/3" in errors.getvalue()


def test_does_not_retry_deterministic_compile_failure():
    calls = []
    sleeps = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return completed(1, stderr="Compilation failed: unresolved reference")

    status = run_gradle_with_retry(
        [":app:assembleDebug"],
        run=fake_run,
        sleep=sleeps.append,
        output_stream=StringIO(),
        error_stream=StringIO(),
    )

    assert status == 1
    assert len(calls) == 1
    assert sleeps == []


def test_stops_after_configured_transient_attempts():
    calls = []
    sleeps = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return completed(1, stderr="Received status code 503: Service Unavailable")

    status = run_gradle_with_retry(
        [":app:testDebugUnitTest"],
        attempts=3,
        base_delay_seconds=2,
        run=fake_run,
        sleep=sleeps.append,
        output_stream=StringIO(),
        error_stream=StringIO(),
    )

    assert status == 1
    assert len(calls) == 3
    assert sleeps == [2, 4]


@pytest.mark.parametrize(
    "arguments,attempts,delay",
    [([], 3, 15), ([":app:test"], 0, 15), ([":app:test"], 3, -1)],
)
def test_rejects_invalid_retry_configuration(arguments, attempts, delay):
    with pytest.raises(ValueError):
        run_gradle_with_retry(
            arguments,
            attempts=attempts,
            base_delay_seconds=delay,
            run=lambda *args, **kwargs: completed(0),
            sleep=lambda _: None,
            output_stream=StringIO(),
            error_stream=StringIO(),
        )
