from types import SimpleNamespace
import subprocess

from agent.android_workmanager_wake import AndroidWorkManagerWakeAdapter


def test_wake_adapter_uses_only_fixed_explicit_broadcast_without_shell():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    adapter = AndroidWorkManagerWakeAdapter(command_runner=runner)

    assert adapter.schedule_next(delay_seconds=900) is True
    command, kwargs = calls[0]
    assert command == [
        "/system/bin/am", "broadcast", "-n",
        "com.mahoraga.runtime/.WakeRequestReceiver",
        "-a", "com.mahoraga.runtime.ENQUEUE_BACKGROUND_WORK",
        "--ei", "delay_seconds", "900",
    ]
    assert kwargs == {
        "capture_output": True,
        "text": True,
        "timeout": 5,
        "check": False,
    }


def test_wake_adapter_rejects_invalid_delays_without_invoking_runner():
    calls = []
    adapter = AndroidWorkManagerWakeAdapter(
        command_runner=lambda *args, **kwargs: calls.append((args, kwargs))
    )

    for value in (True, False, -1, 0, 59, 3601, 900.0, "900", None):
        assert adapter.schedule_next(delay_seconds=value) is False
    assert calls == []


def test_wake_adapter_fails_closed_on_command_error():
    adapter = AndroidWorkManagerWakeAdapter(
        command_runner=lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    assert adapter.schedule_next(delay_seconds=60) is False

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    adapter = AndroidWorkManagerWakeAdapter(command_runner=timeout)
    assert adapter.schedule_next(delay_seconds=60) is False


def test_poll_task_id_is_stable_within_each_fifteen_minute_window():
    from scripts.mahoraga_background_worker import build_poll_task_descriptor

    first = build_poll_task_descriptor(1800000000)
    second = build_poll_task_descriptor(1800000899)
    next_window = build_poll_task_descriptor(1800000900)

    assert first["task_id"] == second["task_id"]
    assert first["task_id"] != next_window["task_id"]
    assert first["checkpointable"] is True
    assert first["risk"] == "local_compute"
    assert first["capability"] == "internal.adopt_next_inquiry"
