from datetime import datetime, timedelta, timezone

import pytest

from agent.background_work_queue import (
    BackgroundWorkQueueConflict,
    BackgroundWorkQueueError,
    BackgroundWorkScheduler,
    PersistentBackgroundWorkQueue,
)
from agent.store import KnowledgeStore


def descriptor(task_id="task-001", **overrides):
    value = {
        "task_id": task_id,
        "name": "internal research",
        "capability": "research.local",
        "args": [],
        "kwargs": {},
        "risk": "local_compute",
        "estimated_runtime_seconds": 10,
        "estimated_ram_mb": 64,
        "checkpointable": True,
        "writes_internal_state": False,
        "priority": "normal",
        "max_attempts": 2,
    }
    value.update(overrides)
    return value


def make_queue(tmp_path):
    store = KnowledgeStore(tmp_path / "queue.sqlite3")
    return PersistentBackgroundWorkQueue(store), store


def test_queue_persists_and_deduplicates_items_across_instances(tmp_path):
    queue, store = make_queue(tmp_path)
    created = queue.enqueue(descriptor())

    assert created["status"] == "enqueued"
    assert created["revision"] == 1
    assert queue.enqueue(descriptor())["status"] == "already_known"

    recovered = PersistentBackgroundWorkQueue(store)
    items = recovered.list_items()
    assert len(items) == 1
    assert items[0]["task_id"] == "task-001"
    assert items[0]["status"] == "queued"
    assert recovered.summary()["queued"] == 1
    assert store.count_events(PersistentBackgroundWorkQueue.EVENT_TYPE) == 1


def test_queue_claims_by_priority_and_reclaims_only_after_lease_expiry(tmp_path):
    queue, store = make_queue(tmp_path)
    now = datetime(2026, 11, 22, 22, 0, tzinfo=timezone.utc)
    queue.enqueue(descriptor("normal"), now=now)
    queue.enqueue(descriptor("high", priority="high"), now=now)

    first = queue.claim_next("worker-a", lease_seconds=15, now=now)
    assert first["task_id"] == "high"
    assert first["attempts"] == 1

    assert queue.claim_next(
        "worker-b", lease_seconds=15, now=now + timedelta(seconds=10)
    )["task_id"] == "normal"
    queue.complete("normal", "worker-b")

    # The high-priority task is still leased and cannot be double-claimed.
    second = queue.claim_next(
        "worker-c", lease_seconds=15, now=now + timedelta(seconds=11)
    )
    assert second is None

    reclaimed = queue.claim_next(
        "worker-c", lease_seconds=15, now=now + timedelta(seconds=16)
    )
    assert reclaimed["task_id"] == "high"
    assert reclaimed["attempts"] == 2

    # A second expired lease exhausts the bounded attempt budget.
    assert queue.claim_next(
        "worker-d", lease_seconds=15, now=now + timedelta(seconds=32)
    ) is None
    assert all(item["task_id"] != "high" for item in queue.list_items())
    recent = store.get_memory(queue.MEMORY_KEY)["value"]["recently_finished"]
    assert any(item["task_id"] == "high" and item["status"] == "failed" for item in recent)


def test_queue_release_requires_lease_owner_and_can_return_unstarted_work(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor())
    claimed = queue.claim_next("worker-a")

    with pytest.raises(BackgroundWorkQueueConflict):
        queue.release("task-001", "worker-b", reason="not owner")

    released = queue.release(
        "task-001", "worker-a", reason="resource gate paused", count_attempt=False
    )
    assert released["status"] == "queued"
    item = queue.list_items()[0]
    assert item["attempts"] == 0
    assert item["worker_id"] is None
    assert item["lease_until"] is None


def test_queue_rejects_external_or_unbounded_task_descriptors(tmp_path):
    queue, _ = make_queue(tmp_path)
    with pytest.raises(BackgroundWorkQueueError):
        queue.enqueue(descriptor(network=True))
    with pytest.raises(BackgroundWorkQueueError):
        queue.enqueue(descriptor("not-checkpointable", checkpointable=False))
    with pytest.raises(BackgroundWorkQueueError):
        queue.enqueue(descriptor("too-large", kwargs={"blob": "x" * 9000}))
    with pytest.raises(BackgroundWorkQueueError):
        queue.enqueue(descriptor("nan", estimated_runtime_seconds=float("nan")))
    assert queue.list_items() == []


class FakeWakeAdapter:
    def __init__(self):
        self.delays = []

    def schedule_next(self, *, delay_seconds):
        self.delays.append(delay_seconds)


class FakeOrchestrator:
    def __init__(self, *, status="completed", error=None, durable_status="not_completed"):
        self.status = status
        self.error = error
        self.durable_status = durable_status
        self.calls = []

    def task_execution_status(self, task_id):
        return self.durable_status

    def run_parallel(self, tasks, **kwargs):
        self.calls.append((tasks, kwargs))
        if self.error is not None:
            raise self.error
        completed = self.status == "completed"
        work_mode = kwargs.get("work_mode", "background_idle")
        return {
            "status": self.status,
            "total": 1,
            "completed": 1 if completed else 0,
            "failed": 0 if completed else 1,
            "tasks": [{
                "id": tasks[0]["id"],
                "status": "completed" if completed else "failed",
                "error": None if completed else "task_failed",
            }],
            "resource_session": {
                "mode": work_mode,
                "status": "bounded",
                "checkpoint_required": work_mode in {"background_idle", "background_companion"},
                "checkpoint_sequence": 1,
            },
            "execution_performed": completed,
        }


def test_scheduler_executes_one_item_per_invocation_and_schedules_next(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor("first"))
    queue.enqueue(descriptor("second"))
    orchestrator = FakeOrchestrator()
    wake = FakeWakeAdapter()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-night", wake)

    first = scheduler.run_once({
        "app_foreground": False,
        "screen_interactive": False,
        "thermal_status": "normal",
    })
    assert first["status"] == "completed"
    assert first["work_mode"] == "background_idle"
    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0][1]["work_mode"] == "background_idle"
    assert wake.delays == [60]
    assert queue.summary()["queued"] == 1

    second = scheduler.run_once({
        "app_foreground": False,
        "screen_interactive": False,
        "thermal_status": "normal",
    })
    assert second["status"] == "completed"
    assert len(orchestrator.calls) == 2
    assert wake.delays == [60]
    assert queue.summary()["active_items"] == 0


@pytest.mark.parametrize(
    "receipt",
    [
        {
            "status": "completed", "total": 1, "completed": 1, "failed": 0,
            "tasks": [{"id": "different-task", "status": "completed", "error": None}],
            "resource_session": {
                "mode": "background_idle", "status": "bounded",
                "checkpoint_required": True, "checkpoint_sequence": 1,
            },
            "execution_performed": True,
        },
        {
            "status": "completed", "total": 1, "completed": 1, "failed": 0,
            "tasks": [],
            "resource_session": {
                "mode": "background_idle", "status": "bounded",
                "checkpoint_required": True, "checkpoint_sequence": 1,
            },
            "execution_performed": True,
        },
        {
            "status": "completed", "total": 1, "completed": 1, "failed": 0,
            "tasks": [{"id": "receipt-check", "status": "completed", "error": None}],
            "resource_session": {
                "mode": "background_idle", "status": "bounded",
                "checkpoint_required": True, "checkpoint_sequence": 0,
            },
            "execution_performed": True,
        },
        {
            "status": "completed", "total": 1, "completed": 1, "failed": 0,
            "tasks": [{"id": "receipt-check", "status": "completed", "error": None}],
            "resource_session": {
                "mode": "background_idle", "status": "bounded",
                "checkpoint_required": True, "checkpoint_sequence": 1,
            },
            "execution_performed": False,
        },
    ],
)
def test_scheduler_retries_instead_of_completing_on_invalid_execution_receipt(tmp_path, receipt):
    class ReceiptOrchestrator(FakeOrchestrator):
        def run_parallel(self, tasks, **kwargs):
            self.calls.append((tasks, kwargs))
            return receipt

    queue, store = make_queue(tmp_path)
    queue.enqueue(descriptor("receipt-check"))
    orchestrator = ReceiptOrchestrator()
    wake = FakeWakeAdapter()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-receipt", wake)

    result = scheduler.run_once({
        "app_foreground": False,
        "screen_interactive": False,
        "charging": True,
        "thermal_status": "normal",
    })

    assert result["status"] == "queued"
    assert result["completion_receipt_valid"] is False
    assert result["reason"] == "invalid_execution_completion_receipt"
    assert queue.list_items()[0]["status"] == "queued"
    assert queue.list_items()[0]["attempts"] == 1
    assert wake.delays == [60]
    recent = store.get_memory(queue.MEMORY_KEY)["value"]["recently_finished"]
    assert recent == []


def test_scheduler_releases_work_when_governor_defers_before_execution(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor())
    orchestrator = FakeOrchestrator(error=PermissionError("charging not confirmed"))
    wake = FakeWakeAdapter()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-night", wake)

    result = scheduler.run_once({"app_foreground": False, "screen_interactive": False})

    assert result["status"] == "deferred"
    assert result["execution_performed"] is False
    assert queue.list_items()[0]["attempts"] == 0
    assert queue.list_items()[0]["status"] == "queued"
    assert wake.delays == [900]


def test_scheduler_reconciles_task_completed_before_worker_process_stopped(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor())
    orchestrator = FakeOrchestrator(durable_status="completed")
    wake = FakeWakeAdapter()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-restart", wake)

    result = scheduler.run_once({"app_foreground": False, "screen_interactive": False})

    assert result["status"] == "completed_reconciled"
    assert result["execution_performed"] is False
    assert orchestrator.calls == []
    assert queue.summary()["active_items"] == 0


def test_scheduler_without_platform_wake_adapter_does_not_claim_continuous_execution(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor("one"))
    queue.enqueue(descriptor("two"))
    scheduler = BackgroundWorkScheduler(queue, FakeOrchestrator(), "worker-no-adapter")

    result = scheduler.run_once({"app_foreground": False, "screen_interactive": False})

    assert result["status"] == "completed"
    assert result["wake_schedule"] == {"status": "adapter_missing", "delay_seconds": None}
    assert queue.summary()["queued"] == 1



def test_queue_rejects_same_task_id_with_different_descriptor(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor("stable-id"))

    with pytest.raises(BackgroundWorkQueueConflict, match="descritor diferente"):
        queue.enqueue(descriptor("stable-id", capability="different.capability"))



def test_queue_rejects_stale_concurrent_writer_without_losing_other_enqueue(tmp_path):
    queue_a, store = make_queue(tmp_path)
    queue_b = PersistentBackgroundWorkQueue(store)
    original = store.compare_and_set_memory_with_event

    def interleaved_commit(key, expected_revision, value, event_type, event_payload, **kwargs):
        if event_payload.get("task_id") == "race-a":
            queue_b.enqueue(descriptor("race-b"))
        return original(
            key, expected_revision, value, event_type, event_payload, **kwargs
        )

    store.compare_and_set_memory_with_event = interleaved_commit
    with pytest.raises(BackgroundWorkQueueConflict):
        queue_a.enqueue(descriptor("race-a"))

    assert [item["task_id"] for item in queue_a.list_items()] == ["race-b"]



class MismatchedCapabilityOrchestrator(FakeOrchestrator):
    def capability_descriptor(self, capability_id):
        return {
            "id": capability_id,
            "risk": "read_only",
            "estimated_runtime_seconds": 10.0,
            "estimated_ram_mb": 64.0,
            "checkpointable": False,
        }


def test_scheduler_terminally_rejects_queue_item_that_mismatches_registered_capability(tmp_path):
    queue, store = make_queue(tmp_path)
    queue.enqueue(descriptor("mismatch"))
    orchestrator = MismatchedCapabilityOrchestrator()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-check")

    result = scheduler.run_once({"app_foreground": False, "screen_interactive": False})

    assert result["status"] == "failed"
    assert orchestrator.calls == []
    assert queue.list_items() == []
    recent = store.get_memory(queue.MEMORY_KEY)["value"]["recently_finished"]
    assert recent[-1]["status"] == "failed"
    assert "does_not_match" in recent[-1]["reason"]



def test_scheduler_keeps_companion_chat_foreground_and_uses_smaller_background_mode(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor("companion"))
    orchestrator = FakeOrchestrator()
    wake = FakeWakeAdapter()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-companion", wake)

    result = scheduler.run_once({
        "app_foreground": False,
        "screen_interactive": True,
        "charging": True,
        "thermal_status": "normal",
    })

    assert result["status"] == "completed"
    assert result["work_mode"] == "background_companion"
    assert orchestrator.calls[0][1]["work_mode"] == "background_companion"


def test_scheduler_defers_when_mahoraga_foreground_or_screen_state_is_unknown(tmp_path):
    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor("defer-companion"))
    orchestrator = FakeOrchestrator()
    wake = FakeWakeAdapter()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-defer", wake)

    result = scheduler.run_once({
        "app_foreground": True,
        "screen_interactive": True,
    })
    unknown = scheduler.run_once({
        "app_foreground": False,
        "screen_interactive": None,
    })

    assert result["status"] == "deferred"
    assert unknown["status"] == "deferred"
    assert orchestrator.calls == []
    item = queue.list_items()[0]
    assert item["attempts"] == 0
    assert item["status"] == "queued"
    assert wake.delays == [900, 900]



def test_queue_persists_internal_write_scope_and_rejects_incompatible_risk(tmp_path):
    queue, store = make_queue(tmp_path)
    created = queue.enqueue(descriptor(
        "internal-write",
        writes_internal_state=True,
        risk="local_compute",
    ))
    assert created["status"] == "enqueued"
    persisted = queue.list_items()[0]
    assert persisted["writes_internal_state"] is True

    with pytest.raises(BackgroundWorkQueueError, match="local_compute"):
        queue.enqueue(descriptor(
            "invalid-internal-write",
            writes_internal_state=True,
            risk="read_only",
        ))

    recovered = PersistentBackgroundWorkQueue(store).list_items()
    assert recovered[0]["writes_internal_state"] is True


def test_scheduler_rejects_internal_write_scope_mismatch_with_registered_capability(tmp_path):
    queue, store = make_queue(tmp_path)
    queue.enqueue(descriptor(
        "internal-write-mismatch",
        writes_internal_state=True,
        risk="local_compute",
    ))
    orchestrator = MismatchedCapabilityOrchestrator()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-scope-mismatch")

    result = scheduler.run_once({
        "app_foreground": False,
        "screen_interactive": False,
    })

    assert result["status"] == "failed"
    assert orchestrator.calls == []
    assert queue.list_items() == []
    recent = store.get_memory(queue.MEMORY_KEY)["value"]["recently_finished"]
    assert recent[-1]["status"] == "failed"
    assert "does_not_match" in recent[-1]["reason"]



def test_legacy_queue_items_default_to_no_internal_write_scope(tmp_path):
    queue, store = make_queue(tmp_path)
    queue.enqueue(descriptor("legacy-item"))
    entry = store.get_memory(queue.MEMORY_KEY)
    value = entry["value"]
    value["items"]["legacy-item"].pop("writes_internal_state", None)
    original_get_memory = store.get_memory

    def legacy_get_memory(key):
        if key == queue.MEMORY_KEY:
            return {**entry, "value": value}
        return original_get_memory(key)

    store.get_memory = legacy_get_memory
    recovered = queue._read()

    assert recovered["items"]["legacy-item"]["writes_internal_state"] is False
    assert queue.enqueue(descriptor("legacy-item"))["status"] == "already_known"



def test_scheduler_executes_internal_write_only_when_registered_scope_matches(tmp_path):
    class InternalWriteOrchestrator(FakeOrchestrator):
        def capability_descriptor(self, capability_id):
            return {
                "id": capability_id,
                "risk": "local_compute",
                "estimated_runtime_seconds": 10.0,
                "estimated_ram_mb": 64.0,
                "checkpointable": True,
                "writes_internal_state": True,
            }

    queue, _ = make_queue(tmp_path)
    queue.enqueue(descriptor(
        "internal-write-match",
        writes_internal_state=True,
        risk="local_compute",
    ))
    orchestrator = InternalWriteOrchestrator()
    wake = FakeWakeAdapter()
    scheduler = BackgroundWorkScheduler(queue, orchestrator, "worker-scope-match", wake)

    result = scheduler.run_once({
        "app_foreground": False,
        "screen_interactive": False,
    })

    assert result["status"] == "completed"
    assert orchestrator.calls[0][0][0]["id"] == "internal-write-match"
    assert orchestrator.calls[0][1]["work_mode"] == "background_idle"
