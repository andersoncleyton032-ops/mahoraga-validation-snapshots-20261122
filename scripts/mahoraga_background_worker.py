#!/usr/bin/env python3
"""One-shot entry point invoked only by the Mahoraga Android WorkManager bridge.

The script seeds at most one deterministic internal-inquiry poll per 15-minute
window, then delegates exactly one queue item to BackgroundWorkScheduler.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULT_PREFIX = "MAHORAGA_WORKER_RESULT:"


def build_worker_id() -> str:
    """Return a unique fencing identity for this process invocation."""
    return f"android-workmanager:{uuid.uuid4().hex}"


def build_poll_task_descriptor(now_epoch: int | float) -> dict[str, Any]:
    if isinstance(now_epoch, bool) or not isinstance(now_epoch, (int, float)):
        raise ValueError("now_epoch inválido.")
    bucket = int(now_epoch // 900)
    return {
        "task_id": f"internal-inquiry-poll:{bucket}",
        "name": "Adopt at most one internal inquiry",
        "capability": "internal.adopt_next_inquiry",
        "args": [],
        "kwargs": {},
        "risk": "local_compute",
        "estimated_runtime_seconds": 8,
        "estimated_ram_mb": 64,
        "checkpointable": True,
        "priority": "normal",
        "max_attempts": 2,
    }


def run_worker_once(
    *,
    core=None,
    now_epoch: int | float | None = None,
    worker_id: str | None = None,
    wake_adapter=None,
) -> dict[str, Any]:
    from agent.android_workmanager_wake import AndroidWorkManagerWakeAdapter
    from agent.background_capabilities import InternalBackgroundCapabilities
    from agent.background_work_queue import (
        BackgroundWorkScheduler,
        PersistentBackgroundWorkQueue,
    )
    from agent.integration_core import IntegratedCore

    runtime = core or IntegratedCore(root=ROOT)
    InternalBackgroundCapabilities(runtime).register()
    queue = PersistentBackgroundWorkQueue(runtime.store)

    if not queue.has_pending():
        timestamp = time.time() if now_epoch is None else now_epoch
        queue.enqueue(build_poll_task_descriptor(timestamp))

    invocation_worker_id = build_worker_id() if worker_id is None else worker_id
    scheduler = BackgroundWorkScheduler(
        queue,
        runtime.research_orchestrator,
        invocation_worker_id,
        wake_adapter or AndroidWorkManagerWakeAdapter(),
    )
    try:
        runtime_context = runtime.hardware.runtime_context()
    except Exception:
        runtime_context = None

    result = scheduler.run_once(runtime_context)
    wake = result.get("wake_schedule")
    return {
        "schema": "mahoraga.background_worker_result.v1",
        "status": str(result.get("status", "unknown"))[:80],
        "task_id": result.get("task_id"),
        "execution_performed": result.get("execution_performed") is True,
        "completion_receipt_valid": result.get("completion_receipt_valid") is True,
        "wake_schedule": wake if isinstance(wake, dict) else {
            "status": "invalid_schedule_receipt",
            "delay_seconds": None,
        },
        "queue": queue.summary(),
    }


def main() -> int:
    try:
        result = run_worker_once()
        print(RESULT_PREFIX + json.dumps(
            result, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ))
        wake_status = result["wake_schedule"].get("status")
        return 2 if wake_status in {
            "adapter_error", "adapter_rejected", "adapter_missing",
            "invalid_delay", "invalid_schedule_receipt",
        } else 0
    except Exception:
        print(RESULT_PREFIX + json.dumps({
            "schema": "mahoraga.background_worker_result.v1",
            "status": "error",
            "execution_performed": False,
            "wake_schedule": {"status": "not_requested", "delay_seconds": None},
        }, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
