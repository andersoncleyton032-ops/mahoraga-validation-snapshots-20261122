"""Fila persistente e integração local de tarefas com o Blender."""

import json
from typing import Any


# Until task-specific approvals and execution receipts are integrated,
# the remote bridge is intentionally read-only.
ALLOWED_TASKS = {
    "scene.inspect",
}


class BlenderTaskQueue:
    """Fila tipada de tarefas armazenada no SQLite compartilhado."""

    def __init__(self, store, dharma):
        self.store = store
        self.dharma = dharma
        self._initialize()

    def _authorize(self, task_type=None, payload=None):
        if task_type == "python.execute":
            payload = payload if isinstance(payload, dict) else {}
            approval_payload = {
                key: value for key, value in payload.items()
                if key not in {"approval_attestation", "human_approved"}
            }
            decision = self.dharma.evaluate(
                "blender_python_execute",
                context={
                    "approval_attestation": payload.get("approval_attestation"),
                    "approval_payload": approval_payload,
                    "scope": payload.get("approval_scope"),
                },
            )
        else:
            decision = self.dharma.evaluate(
                "blender_local_task",
                context={
                    "external_side_effect": False,
                    "writes_project": False,
                    "deletes_data": False,
                    "sensitive_data": False,
                    "irreversible": False,
                },
            )
        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _initialize(self):
        with self.store._transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS blender_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN (
                            'pending', 'claimed',
                            'completed', 'failed'
                        )),
                    worker_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    claimed_at TEXT,
                    finished_at TEXT,
                    result_json TEXT,
                    error TEXT,
                    idempotency_key TEXT UNIQUE
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_blender_tasks_status
                ON blender_tasks(status, id)
            """)

            from .store import utc_now

            db.execute("""
                INSERT INTO metadata(key, value, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
            """, ("blender_bridge_schema", "1", utc_now()))

    @staticmethod
    def _encode(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )

    def submit(self, task_type: str, payload: dict,
               idempotency_key: str | None = None) -> int:

        if task_type not in ALLOWED_TASKS:
            raise ValueError("Tipo de tarefa não autorizado.")

        if not isinstance(payload, dict):
            raise TypeError("O conteúdo da tarefa deve ser um objeto.")

        self._authorize(task_type, payload)
        if task_type == "python.execute":
            # Never persist the one-shot approval credential in the task queue.
            payload = {
                key: value for key, value in payload.items()
                if key not in {"approval_attestation", "human_approved"}
            }
        payload_json = self._encode(payload)

        if len(payload_json.encode("utf-8")) > 65536:
            raise ValueError("Tarefa excede o limite de 64 KB.")

        if idempotency_key is not None:
            idempotency_key = str(idempotency_key).strip()
            if not idempotency_key or len(idempotency_key) > 128:
                raise ValueError("Chave de idempotência inválida.")

        from .store import utc_now

        now = utc_now()

        with self.store._transaction() as db:
            if idempotency_key:
                existing = db.execute(
                    "SELECT id, task_type, payload_json "
                    "FROM blender_tasks WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()

                if existing:
                    if (
                        existing["task_type"] != task_type
                        or existing["payload_json"] != payload_json
                    ):
                        raise ValueError(
                            "Chave de idempotência já usada "
                            "com outra tarefa."
                        )
                    return int(existing["id"])

            cursor = db.execute("""
                INSERT INTO blender_tasks(
                    task_type, payload_json, status,
                    created_at, updated_at, idempotency_key
                ) VALUES (?, ?, 'pending', ?, ?, ?)
            """, (
                task_type,
                payload_json,
                now,
                now,
                idempotency_key,
            ))

            task_id = int(cursor.lastrowid)

        self.store.record_event(
            "blender.task.queued",
            {"task_id": task_id, "task_type": task_type},
        )
        return task_id

    def claim_next(self, worker_id: str) -> dict | None:
        self._authorize()

        worker_id = str(worker_id).strip()
        if not worker_id or len(worker_id) > 120:
            raise ValueError("Identificação do Blender inválida.")

        from .store import utc_now

        now = utc_now()

        with self.store._transaction() as db:
            row = db.execute("""
                SELECT * FROM blender_tasks
                WHERE status='pending'
                ORDER BY id ASC
                LIMIT 1
            """).fetchone()

            if row is None:
                return None

            changed = db.execute("""
                UPDATE blender_tasks
                SET status='claimed',
                    worker_id=?,
                    claimed_at=?,
                    updated_at=?
                WHERE id=? AND status='pending'
            """, (worker_id, now, now, row["id"])).rowcount

            if changed != 1:
                return None

            return {
                "id": int(row["id"]),
                "task_type": row["task_type"],
                "payload": json.loads(row["payload_json"]),
                "worker_id": worker_id,
            }

    def complete(self, task_id: int, result: dict):
        self._authorize()

        if not isinstance(result, dict):
            raise TypeError("O resultado deve ser um objeto.")

        result_json = self._encode(result)
        if len(result_json.encode("utf-8")) > 65536:
            raise ValueError("Resultado excede o limite de 64 KB.")

        from .store import utc_now

        now = utc_now()

        with self.store._transaction() as db:
            changed = db.execute("""
                UPDATE blender_tasks
                SET status='completed',
                    result_json=?,
                    finished_at=?,
                    updated_at=?
                WHERE id=? AND status='claimed'
            """, (result_json, now, now, int(task_id))).rowcount

            if changed != 1:
                raise ValueError(
                    "Tarefa inexistente ou não está em execução."
                )

        self.store.record_event(
            "blender.task.completed",
            {"task_id": int(task_id)},
        )

    def fail(self, task_id: int, error: str):
        self._authorize()

        error = str(error).strip()
        if not error:
            raise ValueError("É necessário informar o erro.")

        error = error[:2000]

        from .store import utc_now

        now = utc_now()

        with self.store._transaction() as db:
            changed = db.execute("""
                UPDATE blender_tasks
                SET status='failed',
                    error=?,
                    finished_at=?,
                    updated_at=?
                WHERE id=? AND status='claimed'
            """, (error, now, now, int(task_id))).rowcount

            if changed != 1:
                raise ValueError(
                    "Tarefa inexistente ou não está em execução."
                )

        self.store.record_event(
            "blender.task.failed",
            {"task_id": int(task_id), "error": error},
            severity="warning",
        )

    def list_tasks(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 200))

        with self.store._reader() as db:
            rows = db.execute("""
                SELECT * FROM blender_tasks
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()

        return [{
            "id": int(row["id"]),
            "task_type": row["task_type"],
            "payload": json.loads(row["payload_json"]),
            "status": row["status"],
            "worker_id": row["worker_id"],
            "result": (
                json.loads(row["result_json"])
                if row["result_json"] else None
            ),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        } for row in rows]

    def status(self) -> dict[str, int]:
        with self.store._reader() as db:
            rows = db.execute("""
                SELECT status, COUNT(*) AS total
                FROM blender_tasks
                GROUP BY status
            """).fetchall()

        result = {
            "pending": 0,
            "claimed": 0,
            "completed": 0,
            "failed": 0,
        }

        for row in rows:
            result[row["status"]] = int(row["total"])

        return result


class BlenderBridge:
    """Fachada do serviço Blender ligada ao núcleo existente."""

    def __init__(self, store, dharma):
        self.store = store
        self.dharma = dharma
        self.queue = BlenderTaskQueue(store, dharma)

    def submit_task(self, task_type, payload, idempotency_key=None):
        return self.queue.submit(
            task_type,
            payload,
            idempotency_key,
        )

    def status(self):
        return self.queue.status()
