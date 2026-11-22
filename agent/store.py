"""Transactional SQLite knowledge store shared by all Mahoraga modules.

The store is the canonical source for new records. Existing JSON files are
imported once and retained as read-only legacy archives.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True, allow_nan=False, default=str)


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Confiança deve ser um número finito entre 0 e 1.")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("Confiança deve ser um número finito entre 0 e 1.") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError("Confiança deve ser um número finito entre 0 e 1.")
    return number


class KnowledgeStore:
    SCHEMA_VERSION = 6

    def __init__(self, db_path: str | Path | None = None):
        root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path).expanduser() if db_path else root / "memory" / "mahoraga.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _reader(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'info',
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    event_id INTEGER NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_sequences (
                    sequence_key TEXT PRIMARY KEY,
                    current_value INTEGER NOT NULL CHECK(current_value >= 0),
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, created_at);
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL,
                    limitations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_observations_category ON observations(category, created_at);
                CREATE TABLE IF NOT EXISTS experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hypothesis TEXT NOT NULL,
                    method TEXT NOT NULL,
                    result TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tools (
                    tool_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    executable_path TEXT,
                    version TEXT,
                    source TEXT NOT NULL DEFAULT 'local-discovery',
                    competence TEXT NOT NULL DEFAULT 'identified',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    limitations_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS self_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legacy_imports (
                    source_path TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    imported_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS installations (
                    installation_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT,
                    method TEXT NOT NULL,
                    source_url TEXT,
                    source_ref TEXT,
                    installed_at TEXT,
                    purpose TEXT NOT NULL,
                    verification TEXT NOT NULL DEFAULT 'not_verified',
                    license TEXT,
                    notes_json TEXT NOT NULL DEFAULT '{}',
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT NOT NULL
                );
            """)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at, description) VALUES (?, ?, ?)",
                (1, utc_now(), "Initial unified knowledge store"),
            )

            connection.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256 TEXT NOT NULL UNIQUE,
                    source_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'prepared',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    imported_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_subject
                ON knowledge_documents(subject, imported_at)
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id)
                        REFERENCES knowledge_documents(id)
                        ON DELETE CASCADE,
                    UNIQUE(document_id, chunk_index)
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
                ON knowledge_chunks(document_id, chunk_index)
            """)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at, description) VALUES (?, ?, ?)",
                (2, utc_now(), "Knowledge Engine document and chunk catalog"),
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    capability_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    maturity_state TEXT NOT NULL,
                    source_module TEXT NOT NULL DEFAULT '',
                    operations_json TEXT NOT NULL DEFAULT '[]',
                    inputs_json TEXT NOT NULL DEFAULT '{}',
                    outputs_json TEXT NOT NULL DEFAULT '{}',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    tools_json TEXT NOT NULL DEFAULT '[]',
                    limitations_json TEXT NOT NULL DEFAULT '[]',
                    resource_requirements_json TEXT NOT NULL DEFAULT '{}',
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_capabilities_state
                ON capabilities(maturity_state, enabled)
            """)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at, description) VALUES (?, ?, ?)",
                (3, utc_now(), "Persistent capability catalog"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at, description) VALUES (?, ?, ?)",
                (4, utc_now(), "Idempotent event recording"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at, description) VALUES (?, ?, ?)",
                (5, utc_now(), "Atomic per-key event sequence allocation"),
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS lab_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    parent_digest TEXT,
                    candidate_digest TEXT,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS lab_experiment_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    event_type TEXT NOT NULL,
                    from_stage TEXT,
                    to_stage TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(experiment_id, sequence),
                    FOREIGN KEY(experiment_id)
                        REFERENCES lab_experiments(experiment_id)
                        ON DELETE RESTRICT
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_lab_experiment_events
                ON lab_experiment_events(experiment_id, sequence)
            """)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at, description) VALUES (?, ?, ?)",
                (6, utc_now(), "Durable append-only experiment ledger with checksummed transitions"),
            )
            connection.commit()
        finally:
            connection.close()

    CAPABILITY_STATES = {
        "planned",
        "in_development",
        "implemented",
        "tested_individually",
        "tested_integration",
        "validated_real",
    }

    def upsert_capability(self, capability_id: str, definition: dict) -> bool:
        """Persist capability metadata without storing executable code."""
        if (
            not isinstance(capability_id, str)
            or not capability_id
            or len(capability_id) > 160
            or capability_id != capability_id.strip()
            or not all(
                ("a" <= c <= "z")
                or ("A" <= c <= "Z")
                or ("0" <= c <= "9")
                or c in "._-"
                for c in capability_id
            )
        ):
            raise ValueError("Identificador de capacidade inválido.")

        if not isinstance(definition, dict):
            raise ValueError("A definição da capacidade precisa ser um dicionário.")

        required_text = ("name", "purpose", "risk", "maturity_state")
        for field in required_text:
            value = definition.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Campo obrigatório inválido: {field}")

        state = definition["maturity_state"].strip()
        if state not in self.CAPABILITY_STATES:
            raise ValueError("Estado de maturidade desconhecido.")

        text_fields = (
            "description", "version", "source_module",
        )
        normalized = {}
        for field in text_fields:
            value = definition.get(
                field,
                "0.1.0" if field == "version" else "",
            )
            if not isinstance(value, str):
                raise ValueError(f"Campo textual inválido: {field}")
            normalized[field] = value.strip()

        normalized.update({
            field: definition[field].strip()
            for field in required_text
        })
        normalized["maturity_state"] = state

        list_fields = (
            "operations", "dependencies", "tools", "limitations",
        )
        dict_fields = (
            "inputs", "outputs", "resource_requirements",
            "validation", "metadata",
        )

        for field in list_fields:
            value = definition.get(field, [])
            if (
                not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
            ):
                raise ValueError(f"Campo de lista inválido: {field}")
            normalized[field] = value

        for field in dict_fields:
            value = definition.get(field, {})
            if not isinstance(value, dict):
                raise ValueError(f"Campo de objeto inválido: {field}")
            normalized[field] = value

        enabled = definition.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("O campo enabled precisa ser booleano.")

        json_fields = (
            "operations", "inputs", "outputs", "dependencies",
            "tools", "limitations", "resource_requirements",
            "validation", "metadata",
        )
        encoded = {}
        for field in json_fields:
            try:
                encoded[field] = json.dumps(
                    normalized[field],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Conteúdo não serializável no campo {field}."
                ) from exc

        now = utc_now()
        with self._transaction() as db:
            exists = db.execute(
                "SELECT 1 FROM capabilities WHERE capability_id = ?",
                (capability_id,),
            ).fetchone() is not None

            db.execute("""
                INSERT INTO capabilities (
                    capability_id, name, purpose, description, version,
                    risk, maturity_state, source_module,
                    operations_json, inputs_json, outputs_json,
                    dependencies_json, tools_json, limitations_json,
                    resource_requirements_json, validation_json,
                    enabled, metadata_json, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(capability_id) DO UPDATE SET
                    name=excluded.name,
                    purpose=excluded.purpose,
                    description=excluded.description,
                    version=excluded.version,
                    risk=excluded.risk,
                    maturity_state=excluded.maturity_state,
                    source_module=excluded.source_module,
                    operations_json=excluded.operations_json,
                    inputs_json=excluded.inputs_json,
                    outputs_json=excluded.outputs_json,
                    dependencies_json=excluded.dependencies_json,
                    tools_json=excluded.tools_json,
                    limitations_json=excluded.limitations_json,
                    resource_requirements_json=excluded.resource_requirements_json,
                    validation_json=excluded.validation_json,
                    enabled=excluded.enabled,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
            """, (
                capability_id,
                normalized["name"],
                normalized["purpose"],
                normalized["description"],
                normalized["version"],
                normalized["risk"],
                normalized["maturity_state"],
                normalized["source_module"],
                encoded["operations"],
                encoded["inputs"],
                encoded["outputs"],
                encoded["dependencies"],
                encoded["tools"],
                encoded["limitations"],
                encoded["resource_requirements"],
                encoded["validation"],
                int(enabled),
                encoded["metadata"],
                now,
                now,
            ))

        return not exists

    def list_capabilities(self, enabled_only: bool = False) -> list[dict]:
        """Return persistent capability metadata, never executable functions."""
        if not isinstance(enabled_only, bool):
            raise ValueError("enabled_only precisa ser booleano.")

        query = "SELECT * FROM capabilities"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY capability_id"

        json_fields = {
            "operations": "operations_json",
            "inputs": "inputs_json",
            "outputs": "outputs_json",
            "dependencies": "dependencies_json",
            "tools": "tools_json",
            "limitations": "limitations_json",
            "resource_requirements": "resource_requirements_json",
            "validation": "validation_json",
            "metadata": "metadata_json",
        }

        with self._reader() as db:
            rows = db.execute(query).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            for field, column in json_fields.items():
                item[field] = json.loads(item.pop(column))
            item["enabled"] = bool(item["enabled"])
            result.append(item)
        return result

    def save_memory(self, key: str, value: Any, metadata: dict | None = None) -> None:
        key = str(key).strip()
        if not key or len(key) > 200:
            raise ValueError("A chave da memória deve conter de 1 a 200 caracteres.")
        now = utc_now()
        with self._transaction() as db:
            db.execute("""INSERT INTO memories(key,value_json,metadata_json,created_at,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                value_json=excluded.value_json, metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at""",
                (key, _json(value), _json(metadata or {}), now, now))
            db.execute(
                "INSERT INTO events(event_type,severity,payload_json,created_at) VALUES(?,?,?,?)",
                ("memory.saved", "info", _json({"key": key}), now),
            )

    def load_memories(self) -> dict[str, dict]:
        with self._reader() as db:
            rows = db.execute("SELECT key,value_json,updated_at,metadata_json FROM memories ORDER BY key").fetchall()
        result = {}
        for row in rows:
            result[row["key"]] = {
                "value": json.loads(row["value_json"]),
                "updated_at": row["updated_at"],
                "metadata": json.loads(row["metadata_json"]),
            }
        return result

    def save_memory_if_absent(
        self, key: str, value: Any, metadata: dict | None = None
    ) -> bool:
        """Atomically create a memory entry and its event only when absent."""
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError("A chave da memória deve conter de 1 a 200 caracteres.")
        normalized_key = key.strip()
        now = utc_now()
        with self._transaction() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO memories(
                    key,value_json,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?)""",
                (
                    normalized_key,
                    _json(value),
                    _json(metadata or {}),
                    now,
                    now,
                ),
            )
            created = cursor.rowcount == 1
            if created:
                db.execute(
                    "INSERT INTO events(event_type,severity,payload_json,created_at) VALUES(?,?,?,?)",
                    ("memory.saved", "info", _json({"key": normalized_key}), now),
                )
        return created

    def get_memory(self, key: str) -> dict | None:
        """Read one memory entry without loading the complete memory catalog."""
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError("A chave da memória deve conter de 1 a 200 caracteres.")
        with self._reader() as db:
            row = db.execute(
                "SELECT key,value_json,updated_at,metadata_json FROM memories WHERE key=?",
                (key.strip(),),
            ).fetchone()
        if row is None:
            return None
        return {
            "value": json.loads(row["value_json"]),
            "updated_at": row["updated_at"],
            "metadata": json.loads(row["metadata_json"]),
        }

    def record_event_once(
        self,
        event_type: str,
        idempotency_key: str,
        payload: dict | None = None,
        severity: str = "info",
    ) -> dict:
        """Append an event once per stable key, atomically across Store instances.

        Reusing a key with a different event payload is rejected rather than
        silently returning an unrelated prior result.
        """
        if not isinstance(event_type, str) or not event_type.strip() or len(event_type) > 120:
            raise ValueError("Tipo de evento inválido.")
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key) > 200
        ):
            raise ValueError("idempotency_key deve conter de 1 a 200 caracteres.")
        if not isinstance(severity, str) or not severity.strip() or len(severity) > 20:
            raise ValueError("severity inválida.")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload deve ser um dicionário ou None.")

        normalized_key = idempotency_key.strip()
        normalized_type = event_type.strip()
        normalized_severity = severity.strip()
        payload_json = _json(payload or {})
        fingerprint = hashlib.sha256(
            _json({
                "event_type": normalized_type,
                "severity": normalized_severity,
                "payload_json": payload_json,
            }).encode("utf-8")
        ).hexdigest()
        now = utc_now()

        with self._transaction() as db:
            existing = db.execute(
                "SELECT payload_sha256,event_id FROM event_idempotency WHERE idempotency_key=?",
                (normalized_key,),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != fingerprint:
                    raise ValueError(
                        "idempotency_key já foi usada com outro conteúdo."
                    )
                return {
                    "event_id": int(existing["event_id"]),
                    "created": False,
                    "idempotency_key": normalized_key,
                }

            cursor = db.execute(
                "INSERT INTO events(event_type,severity,payload_json,created_at) VALUES(?,?,?,?)",
                (normalized_type, normalized_severity, payload_json, now),
            )
            event_id = int(cursor.lastrowid)
            db.execute(
                """INSERT INTO event_idempotency(
                    idempotency_key,payload_sha256,event_id,created_at
                ) VALUES(?,?,?,?)""",
                (normalized_key, fingerprint, event_id, now),
            )

        return {
            "event_id": event_id,
            "created": True,
            "idempotency_key": normalized_key,
        }

    def record_event(self, event_type: str, payload: dict | None = None, severity: str = "info") -> int:
        if not isinstance(event_type, str) or not event_type.strip() or len(event_type) > 120:
            raise ValueError("Tipo de evento inválido.")
        if not isinstance(severity, str) or not severity.strip() or len(severity) > 20:
            raise ValueError("severity inválida.")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload deve ser um dicionário ou None.")
        with self._transaction() as db:
            cursor = db.execute("INSERT INTO events(event_type,severity,payload_json,created_at) VALUES(?,?,?,?)",
                                (event_type, severity, _json(payload or {}), utc_now()))
            return int(cursor.lastrowid)

    def record_sequenced_event(
        self,
        event_type: str,
        sequence_key: str,
        payload: dict | None = None,
        *,
        sequence_field: str = "sequence",
        severity: str = "info",
    ) -> dict:
        """Allocate a monotonic sequence and append its event in one SQLite transaction.

        BEGIN IMMEDIATE serializes allocation across independent connections and
        processes sharing this database file.
        """
        if not isinstance(event_type, str) or not event_type.strip() or len(event_type) > 120:
            raise ValueError("Tipo de evento inválido.")
        if not isinstance(sequence_key, str) or not sequence_key.strip() or len(sequence_key) > 200:
            raise ValueError("sequence_key deve conter de 1 a 200 caracteres.")
        if (
            not isinstance(sequence_field, str)
            or not sequence_field
            or len(sequence_field) > 80
            or not sequence_field.replace("_", "").isalnum()
        ):
            raise ValueError("sequence_field inválido.")
        if not isinstance(severity, str) or not severity.strip() or len(severity) > 20:
            raise ValueError("severity inválida.")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload deve ser um dicionário ou None.")

        normalized_key = sequence_key.strip()
        normalized_type = event_type.strip()
        normalized_severity = severity.strip()
        event_payload = dict(payload or {})
        if sequence_field in event_payload:
            raise ValueError("payload não pode definir o campo de sequência.")

        with self._transaction() as db:
            row = db.execute(
                "SELECT current_value FROM event_sequences WHERE sequence_key=?",
                (normalized_key,),
            ).fetchone()
            next_value = int(row["current_value"]) + 1 if row else 1

            if row is None:
                db.execute(
                    "INSERT INTO event_sequences(sequence_key,current_value,updated_at) VALUES(?,?,?)",
                    (normalized_key, next_value, utc_now()),
                )
            else:
                db.execute(
                    "UPDATE event_sequences SET current_value=?,updated_at=? WHERE sequence_key=?",
                    (next_value, utc_now(), normalized_key),
                )

            event_payload[sequence_field] = next_value
            cursor = db.execute(
                "INSERT INTO events(event_type,severity,payload_json,created_at) VALUES(?,?,?,?)",
                (normalized_type, normalized_severity, _json(event_payload), utc_now()),
            )
            return {
                "event_id": int(cursor.lastrowid),
                "sequence": next_value,
                "sequence_key": normalized_key,
            }

    def get_event(self, event_id: int) -> dict | None:
        """Read one immutable event by ID without loading the event catalog."""
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
            raise ValueError("event_id deve ser um inteiro positivo.")
        with self._reader() as db:
            row = db.execute(
                "SELECT * FROM events WHERE id=?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "event_type": row["event_type"],
            "severity": row["severity"],
            "payload": payload,
            "created_at": row["created_at"],
        }

    def get_events(self, event_ids: list[int] | tuple[int, ...]) -> dict[int, dict]:
        """Read a bounded set of immutable events in one SQLite snapshot.

        The input is capped at 3,000 IDs and queried in chunks of 500 to stay
        below conservative SQLite variable limits. Missing IDs are omitted.
        """
        if not isinstance(event_ids, (list, tuple)):
            raise ValueError("event_ids deve ser uma lista ou tupla.")
        if len(event_ids) > 3000:
            raise ValueError("event_ids excede o limite de 3000 registros.")

        normalized = set()
        for event_id in event_ids:
            if (
                isinstance(event_id, bool)
                or not isinstance(event_id, int)
                or not 0 < event_id <= 9_223_372_036_854_775_807
            ):
                raise ValueError("Cada event_id deve ser um inteiro positivo do SQLite.")
            normalized.add(event_id)
        if not normalized:
            return {}

        result = {}
        ordered_ids = sorted(normalized)
        with self._reader() as db:
            db.execute("BEGIN")
            for offset in range(0, len(ordered_ids), 500):
                batch = ordered_ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = db.execute(
                    f"SELECT * FROM events WHERE id IN ({placeholders})",
                    tuple(batch),
                ).fetchall()
                for row in rows:
                    event_id = int(row["id"])
                    result[event_id] = {
                        "id": event_id,
                        "event_type": row["event_type"],
                        "severity": row["severity"],
                        "payload": json.loads(row["payload_json"]),
                        "created_at": row["created_at"],
                    }
        return result

    def count_events(self, event_type: str | None = None) -> int:
        """Count events using SQL aggregation without decoding event payloads."""
        if event_type is not None and (
            not isinstance(event_type, str) or not event_type.strip() or len(event_type) > 120
        ):
            raise ValueError("event_type deve ser texto não vazio ou None.")
        with self._reader() as db:
            if event_type is None:
                row = db.execute("SELECT COUNT(*) AS total FROM events").fetchone()
            else:
                row = db.execute(
                    "SELECT COUNT(*) AS total FROM events WHERE event_type=?",
                    (event_type.strip(),),
                ).fetchone()
        return int(row["total"])

    def count_memories(self) -> int:
        """Count persistent memory keys without decoding their stored values."""
        with self._reader() as db:
            row = db.execute("SELECT COUNT(*) AS total FROM memories").fetchone()
        return int(row["total"])

    def list_memory_metadata(self, limit: int = 100) -> list[dict]:
        """List bounded memory metadata without reading value_json."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit deve ser um inteiro entre 1 e 1000.")
        with self._reader() as db:
            rows = db.execute(
                """SELECT key, created_at, updated_at
                   FROM memories
                   ORDER BY updated_at DESC, key ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "key": row["key"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def list_event_metadata(
        self, limit: int = 100, event_type: str | None = None
    ) -> list[dict]:
        """List bounded event envelopes without decoding payload_json."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit deve ser um inteiro entre 1 e 1000.")
        if event_type is not None and (
            not isinstance(event_type, str)
            or not event_type.strip()
            or len(event_type) > 120
        ):
            raise ValueError("event_type deve ser texto não vazio ou None.")
        with self._reader() as db:
            if event_type is None:
                rows = db.execute(
                    """SELECT id, event_type, severity, created_at
                       FROM events ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT id, event_type, severity, created_at
                       FROM events WHERE event_type=?
                       ORDER BY id DESC LIMIT ?""",
                    (event_type.strip(), limit),
                ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "severity": row["severity"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_events(self, limit: int = 100, event_type: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        with self._reader() as db:
            if event_type:
                rows = db.execute("SELECT * FROM events WHERE event_type=? ORDER BY id DESC LIMIT ?",
                                  (event_type, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "event_type": r["event_type"], "severity": r["severity"],
                 "payload": json.loads(r["payload_json"]), "created_at": r["created_at"]} for r in rows]

    def list_observations(
        self, limit: int = 100, category: str | None = None
    ) -> list[dict]:
        """Return recent observations without modifying the canonical store."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise ValueError("limit deve ser um inteiro entre 1 e 1000.")
        if category is not None and (
            not isinstance(category, str) or not category.strip()
        ):
            raise ValueError("category deve ser texto não vazio ou None.")
        with self._reader() as db:
            if category is None:
                rows = db.execute(
                    "SELECT * FROM observations ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM observations WHERE category=? "
                    "ORDER BY id DESC LIMIT ?",
                    (category.strip(), limit),
                ).fetchall()
        return [
            {
                "id": row["id"],
                "category": row["category"],
                "subject": row["subject"],
                "data": json.loads(row["data_json"]),
                "source": row["source"],
                "confidence": row["confidence"],
                "limitations": json.loads(row["limitations_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_observation(self, category: str, subject: str, data: Any, source: str,
                           confidence: float | None = None, limitations: list[str] | None = None) -> int:
        confidence = _confidence(confidence)
        if not all(
            isinstance(value, str) and value.strip()
            for value in (category, subject, source)
        ):
            raise ValueError("category, subject e source precisam ser textos não vazios.")
        with self._transaction() as db:
            cursor = db.execute("""INSERT INTO observations(category,subject,data_json,source,confidence,
                limitations_json,created_at) VALUES(?,?,?,?,?,?,?)""",
                (category, subject, _json(data), source, confidence, _json(limitations or []), utc_now()))
            return int(cursor.lastrowid)


    def record_observation_and_event(
        self, category: str, subject: str, data: Any, source: str,
        event_type: str, event_payload: dict | None = None,
        confidence: float | None = None,
        limitations: list[str] | None = None,
        severity: str = "info",
    ) -> dict[str, int]:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (category, subject, source, event_type)
        ):
            raise ValueError("category, subject, source e event_type precisam ser textos não vazios.")
        if len(event_type) > 120:
            raise ValueError("Tipo de evento inválido.")
        if event_payload is not None and not isinstance(event_payload, dict):
            raise ValueError("event_payload deve ser um dicionário ou None.")
        if not isinstance(severity, str) or not severity.strip() or len(severity) > 20:
            raise ValueError("severity inválida.")
        confidence = _confidence(confidence)
        data_json = _json(data)
        limitations_json = _json(limitations or [])
        payload_json = _json(event_payload or {})
        now = utc_now()
        with self._transaction() as db:
            observation = db.execute(
                """INSERT INTO observations(category,subject,data_json,
                source,confidence,limitations_json,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (category, subject, data_json, source, confidence,
                 limitations_json, now))
            event = db.execute(
                """INSERT INTO events(event_type,severity,payload_json,created_at)
                VALUES(?,?,?,?)""",
                (event_type, severity, payload_json, now))
            return {"observation_id": int(observation.lastrowid),
                    "event_id": int(event.lastrowid)}

    LAB_EXPERIMENT_STAGES = {
        "proposed", "triaged", "sandboxed", "tested",
        "review_ready", "rejected", "quarantined",
    }
    LAB_EXPERIMENT_TRANSITIONS = {
        "proposed": {"triaged", "rejected"},
        "triaged": {"sandboxed", "rejected"},
        "sandboxed": {"tested", "rejected", "quarantined"},
        "tested": {"review_ready", "rejected", "quarantined"},
        "review_ready": {"quarantined"},
        "rejected": set(),
        "quarantined": set(),
    }
    LAB_EXPERIMENT_SCHEMA_VERSION = 1
    LAB_EXPERIMENT_MAX_PAYLOAD_BYTES = 64 * 1024

    @staticmethod
    def _lab_payload_json(payload: dict) -> str:
        if not isinstance(payload, dict):
            raise ValueError("Payload do experimento precisa ser um objeto JSON.")
        budget = [0]

        def validate(value, depth=0):
            if depth > 16:
                raise ValueError("Profundidade excessiva no payload do experimento.")
            budget[0] += 1
            if budget[0] > 10_000:
                raise ValueError("Payload do experimento excede o limite de nós.")
            if value is None or isinstance(value, (bool, str)):
                if isinstance(value, str) and len(value) > 16_384:
                    raise ValueError("Texto excessivo no payload do experimento.")
                return
            if isinstance(value, int) and not isinstance(value, bool):
                if value.bit_length() > 4096:
                    raise ValueError("Inteiro excessivo no payload do experimento.")
                return
            if isinstance(value, float):
                if not math.isfinite(value):
                    raise ValueError("Número não finito no payload do experimento.")
                return
            if isinstance(value, list):
                for item in value:
                    validate(item, depth + 1)
                return
            if isinstance(value, dict):
                for key, item in value.items():
                    if not isinstance(key, str) or len(key) > 256:
                        raise ValueError("Chave inválida no payload do experimento.")
                    validate(item, depth + 1)
                return
            raise ValueError("Tipo não JSON permitido no payload do experimento.")

        validate(payload)
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"),
            sort_keys=True, allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > KnowledgeStore.LAB_EXPERIMENT_MAX_PAYLOAD_BYTES:
            raise ValueError("Payload do experimento excede 64 KiB.")
        return encoded

    @staticmethod
    def _lab_digest(encoded: str) -> str:
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _lab_validate_id(experiment_id: str) -> str:
        if (
            not isinstance(experiment_id, str)
            or not experiment_id
            or len(experiment_id) > 128
            or any(not (char.isalnum() or char in "._-") for char in experiment_id)
        ):
            raise ValueError("experiment_id inválido.")
        return experiment_id

    @staticmethod
    def _lab_record_digest(
        experiment_id: str, schema_version: int, stage: str, version: int,
        parent_digest: str | None, candidate_digest: str | None,
        payload_json: str,
    ) -> str:
        envelope = json.dumps({
            "experiment_id": experiment_id,
            "schema_version": schema_version,
            "stage": stage,
            "version": version,
            "parent_digest": parent_digest,
            "candidate_digest": candidate_digest,
            "payload_json": payload_json,
        }, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(envelope.encode("utf-8")).hexdigest()

    @staticmethod
    def _lab_event_digest(
        sequence: int, event_type: str, from_stage: str | None,
        to_stage: str, payload_json: str, created_at: str,
    ) -> str:
        envelope = json.dumps({
            "sequence": sequence, "event_type": event_type,
            "from_stage": from_stage, "to_stage": to_stage,
            "payload_json": payload_json, "created_at": created_at,
        }, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(envelope.encode("utf-8")).hexdigest()

    def create_lab_experiment(
        self, experiment_id: str, payload: dict, *,
        parent_digest: str | None = None,
    ) -> dict:
        """Create a durable experiment record and sequence-1 event atomically."""
        experiment_id = self._lab_validate_id(experiment_id)
        if parent_digest is not None and (
            not isinstance(parent_digest, str)
            or len(parent_digest) != 64
            or any(char not in "0123456789abcdef" for char in parent_digest)
        ):
            raise ValueError("parent_digest precisa ser SHA-256 hexadecimal.")
        if not isinstance(payload, dict):
            raise ValueError("Payload do experimento precisa ser um objeto JSON.")
        clean_payload = dict(payload)
        if "stage" in clean_payload and clean_payload["stage"] != "proposed":
            raise ValueError("Novo experimento precisa iniciar em proposed.")
        clean_payload["stage"] = "proposed"
        payload_json = self._lab_payload_json(clean_payload)
        now = utc_now()
        digest = self._lab_record_digest(
            experiment_id, self.LAB_EXPERIMENT_SCHEMA_VERSION, "proposed", 1,
            parent_digest, None, payload_json,
        )
        event_payload = {
            "experiment_id": experiment_id,
            "version": 1,
            "stage": "proposed",
            "payload_sha256": digest,
            "parent_digest": parent_digest,
        }
        event_json = self._lab_payload_json(event_payload)
        event_digest = self._lab_event_digest(
            1, "created", None, "proposed", event_json, now,
        )
        with self._transaction() as db:
            db.execute(
                """INSERT INTO lab_experiments(
                    experiment_id,schema_version,stage,version,parent_digest,
                    candidate_digest,payload_json,payload_sha256,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (experiment_id, self.LAB_EXPERIMENT_SCHEMA_VERSION, "proposed", 1,
                 parent_digest, None, payload_json, digest, now, now),
            )
            db.execute(
                """INSERT INTO lab_experiment_events(
                    experiment_id,sequence,event_type,from_stage,to_stage,
                    payload_json,payload_sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (experiment_id, 1, "created", None, "proposed",
                 event_json, event_digest, now),
            )
        return {
            "experiment_id": experiment_id, "stage": "proposed", "version": 1,
            "payload_sha256": digest, "parent_digest": parent_digest,
            "created_at": now, "updated_at": now,
        }

    def create_lab_experiment_once(
        self, experiment_id: str, payload: dict, *,
        parent_digest: str | None = None,
    ) -> dict:
        """Idempotently create a cycle-scoped experiment, rejecting ID reuse."""
        experiment_id = self._lab_validate_id(experiment_id)
        normalized_payload = dict(payload) if isinstance(payload, dict) else payload
        if isinstance(normalized_payload, dict):
            normalized_payload["stage"] = "proposed"
        expected_json = self._lab_payload_json(normalized_payload)
        try:
            created = self.create_lab_experiment(
                experiment_id, normalized_payload, parent_digest=parent_digest,
            )
            return {"created": True, "record": self.get_lab_experiment(experiment_id)}
        except sqlite3.IntegrityError:
            existing = self.get_lab_experiment(experiment_id)
            if existing is None:
                raise
            if (
                self._lab_payload_json(existing["payload"]) != expected_json
                or existing["parent_digest"] != parent_digest
            ):
                raise ValueError(
                    "experiment_id já foi usado com conteúdo ou linhagem diferentes."
                )
            return {"created": False, "record": existing}

    def transition_lab_experiment(
        self, experiment_id: str, *, expected_version: int,
        expected_stage: str, new_stage: str, evidence: dict,
        candidate_digest: str | None = None,
    ) -> dict:
        """Atomically append a checksummed lifecycle transition using CAS."""
        experiment_id = self._lab_validate_id(experiment_id)
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected_version precisa ser inteiro positivo.")
        if (
            not isinstance(expected_stage, str) or not isinstance(new_stage, str)
            or expected_stage not in self.LAB_EXPERIMENT_STAGES
            or new_stage not in self.LAB_EXPERIMENT_STAGES
        ):
            raise ValueError("Estado de experimento desconhecido.")
        if new_stage not in self.LAB_EXPERIMENT_TRANSITIONS[expected_stage]:
            raise ValueError("Transição de estado não permitida.")
        if candidate_digest is not None and (
            not isinstance(candidate_digest, str) or len(candidate_digest) != 64
            or any(char not in "0123456789abcdef" for char in candidate_digest)
        ):
            raise ValueError("candidate_digest precisa ser SHA-256 hexadecimal.")
        evidence_json = self._lab_payload_json(evidence)
        if new_stage == "tested":
            passed = evidence.get("tests_passed")
            total = evidence.get("tests_total")
            if (
                isinstance(passed, bool) or not isinstance(passed, int)
                or isinstance(total, bool) or not isinstance(total, int)
                or total < 1 or passed != total
                or candidate_digest is None
            ):
                raise ValueError("Estado tested exige todos os testes aprovados e candidate_digest.")
        if new_stage == "review_ready":
            review_ref = evidence.get("independent_review_ref")
            if not isinstance(review_ref, str) or not review_ref.strip():
                raise ValueError("review_ready exige referência de revisão independente.")
        now = utc_now()
        with self._transaction() as db:
            row = db.execute(
                "SELECT * FROM lab_experiments WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            if row is None:
                raise KeyError(experiment_id)
            actual_record_digest = self._lab_record_digest(
                row["experiment_id"], row["schema_version"], row["stage"],
                row["version"], row["parent_digest"], row["candidate_digest"],
                row["payload_json"],
            )
            if actual_record_digest != row["payload_sha256"]:
                raise sqlite3.DatabaseError("Checksum do registro do experimento inválido.")
            if row["version"] != expected_version or row["stage"] != expected_stage:
                raise ValueError("Conflito de versão/estado; recarregue antes de transicionar.")
            event_row = db.execute(
                "SELECT COALESCE(MAX(sequence),0) AS seq FROM lab_experiment_events WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            sequence = int(event_row["seq"]) + 1
            next_version = int(row["version"]) + 1
            event_payload = {
                "experiment_id": experiment_id,
                "version": next_version,
                "evidence": evidence,
                "candidate_digest": candidate_digest,
            }
            event_json = self._lab_payload_json(event_payload)
            event_digest = self._lab_event_digest(
                sequence, "transition", expected_stage, new_stage, event_json, now,
            )
            next_candidate_digest = candidate_digest or row["candidate_digest"]
            next_record_digest = self._lab_record_digest(
                experiment_id, int(row["schema_version"]), new_stage, next_version,
                row["parent_digest"], next_candidate_digest, row["payload_json"],
            )
            db.execute(
                """INSERT INTO lab_experiment_events(
                    experiment_id,sequence,event_type,from_stage,to_stage,
                    payload_json,payload_sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (experiment_id, sequence, "transition", expected_stage, new_stage,
                 event_json, event_digest, now),
            )
            db.execute(
                """UPDATE lab_experiments SET stage=?,version=?,candidate_digest=?,
                    payload_sha256=?,updated_at=?
                    WHERE experiment_id=? AND version=? AND stage=?""",
                (new_stage, next_version, next_candidate_digest, next_record_digest,
                 now, experiment_id, expected_version, expected_stage),
            )
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("Conflito de versão durante a transição do experimento.")
        return {
            "experiment_id": experiment_id, "stage": new_stage,
            "version": next_version, "candidate_digest": candidate_digest,
            "updated_at": now,
        }

    def get_lab_experiment(self, experiment_id: str) -> dict | None:
        experiment_id = self._lab_validate_id(experiment_id)
        with self._reader() as db:
            row = db.execute(
                "SELECT * FROM lab_experiments WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        if self._lab_record_digest(
            row["experiment_id"], row["schema_version"], row["stage"],
            row["version"], row["parent_digest"], row["candidate_digest"],
            row["payload_json"],
        ) != row["payload_sha256"]:
            raise sqlite3.DatabaseError("Checksum do registro do experimento inválido.")
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise sqlite3.DatabaseError("Payload atual do experimento não é um objeto.")
        return {
            "experiment_id": row["experiment_id"],
            "schema_version": row["schema_version"], "stage": row["stage"],
            "version": row["version"], "parent_digest": row["parent_digest"],
            "candidate_digest": row["candidate_digest"],
            "payload": json.loads(row["payload_json"]),
            "payload_sha256": row["payload_sha256"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def list_lab_experiments(self, limit: int = 100) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit precisa estar entre 1 e 500.")
        with self._reader() as db:
            rows = db.execute(
                "SELECT experiment_id FROM lab_experiments ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self.get_lab_experiment(row["experiment_id"]) for row in rows]

    def get_lab_experiment_history(self, experiment_id: str) -> list[dict]:
        experiment_id = self._lab_validate_id(experiment_id)
        with self._reader() as db:
            rows = db.execute(
                "SELECT * FROM lab_experiment_events WHERE experiment_id=? ORDER BY sequence",
                (experiment_id,),
            ).fetchall()
        history = []
        for expected_sequence, row in enumerate(rows, 1):
            if row["sequence"] != expected_sequence:
                raise sqlite3.DatabaseError("Sequência do histórico de experimento contém lacuna.")
            if self._lab_event_digest(
                row["sequence"], row["event_type"], row["from_stage"],
                row["to_stage"], row["payload_json"], row["created_at"],
            ) != row["payload_sha256"]:
                raise sqlite3.DatabaseError("Checksum do histórico de experimento inválido.")
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                raise sqlite3.DatabaseError("Payload de evento do experimento não é um objeto.")
            history.append({
                "sequence": row["sequence"], "event_type": row["event_type"],
                "from_stage": row["from_stage"], "to_stage": row["to_stage"],
                "payload": payload,
                "payload_sha256": row["payload_sha256"], "created_at": row["created_at"],
            })
        return history

    def audit_lab_experiments(self, limit: int = 500) -> dict:
        """Verify current payloads and contiguous append-only event histories."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit precisa estar entre 1 e 500.")
        with self._reader() as db:
            ids = [row["experiment_id"] for row in db.execute(
                "SELECT experiment_id FROM lab_experiments ORDER BY created_at LIMIT ?",
                (limit + 1,),
            ).fetchall()]
        truncated = len(ids) > limit
        ids = ids[:limit]
        valid, invalid = [], []
        for experiment_id in ids:
            try:
                current = self.get_lab_experiment(experiment_id)
                history = self.get_lab_experiment_history(experiment_id)
                if not history:
                    raise sqlite3.DatabaseError("Histórico do experimento está vazio.")
                previous_stage = None
                for sequence, event in enumerate(history, 1):
                    payload = event["payload"]
                    if payload.get("version") != sequence:
                        raise sqlite3.DatabaseError("Versão do histórico não é sequencial.")
                    if payload.get("experiment_id") != experiment_id:
                        raise sqlite3.DatabaseError("ID do histórico diverge do registro.")
                    if sequence == 1:
                        if (
                            event["event_type"] != "created"
                            or event["from_stage"] is not None
                            or event["to_stage"] != "proposed"
                            or payload.get("stage") != "proposed"
                            or payload.get("parent_digest") != current["parent_digest"]
                        ):
                            raise sqlite3.DatabaseError("Evento inicial do experimento é inválido.")
                    else:
                        if (
                            event["event_type"] != "transition"
                            or event["from_stage"] != previous_stage
                            or event["to_stage"] not in self.LAB_EXPERIMENT_TRANSITIONS.get(previous_stage, set())
                        ):
                            raise sqlite3.DatabaseError("Transição no histórico é inválida.")
                    previous_stage = event["to_stage"]
                if (
                    history[-1]["to_stage"] != current["stage"]
                    or history[-1]["payload"]["version"] != current["version"]
                    or history[-1]["payload"].get("candidate_digest") != current["candidate_digest"]
                ):
                    raise sqlite3.DatabaseError("Estado atual diverge do último evento.")
                if any(
                    event["payload"].get("candidate_digest") is not None
                    for event in history[:-1]
                ) and current["candidate_digest"] is None:
                    raise sqlite3.DatabaseError("Digest do candidato foi removido do estado atual.")
                valid.append(experiment_id)
            except (sqlite3.DatabaseError, ValueError, KeyError) as exc:
                invalid.append({"experiment_id": experiment_id, "reason": str(exc)})
        return {
            "checked": len(ids), "valid": valid, "invalid": invalid,
            "truncated": truncated,
        }

    def record_experiment(self, hypothesis: str, method: str, result: str, conclusion: str,
                          metadata: dict | None = None, created_at: str | None = None) -> int:
        if not all(str(x).strip() for x in (hypothesis, method, result, conclusion)):
            raise ValueError("Experimento exige hipótese, método, resultado e conclusão.")
        with self._transaction() as db:
            cursor = db.execute("""INSERT INTO experiments(hypothesis,method,result,conclusion,
                metadata_json,created_at) VALUES(?,?,?,?,?,?)""",
                (hypothesis, method, result, conclusion, _json(metadata or {}), created_at or utc_now()))
            return int(cursor.lastrowid)

    def list_experiments(self, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        with self._reader() as db:
            rows = db.execute("SELECT * FROM experiments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "hypothesis": r["hypothesis"], "method": r["method"],
                 "result": r["result"], "conclusion": r["conclusion"],
                 "metadata": json.loads(r["metadata_json"]), "created_at": r["created_at"]} for r in rows]

    def upsert_tool(self, tool_id: str, name: str, executable_path: str | None,
                    version: str | None = None, source: str = "local-discovery",
                    competence: str = "identified", evidence: list | None = None,
                    limitations: list | None = None, metadata: dict | None = None) -> None:
        now = utc_now()
        with self._transaction() as db:
            db.execute("""INSERT INTO tools(tool_id,name,executable_path,version,source,competence,
                evidence_json,limitations_json,metadata_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(tool_id) DO UPDATE SET name=excluded.name,
                executable_path=excluded.executable_path,version=excluded.version,
                source=excluded.source,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                (tool_id, name, executable_path, version, source, competence,
                 _json(evidence or []), _json(limitations or []), _json(metadata or {}), now))

    def update_tool_competence(self, tool_id: str, competence: str, evidence: list[str]) -> None:
        allowed = ("identified", "studied", "experimented", "operational", "specialized", "improver")
        if competence not in allowed:
            raise ValueError("Nível de competência desconhecido.")
        if not isinstance(evidence, list) or any(not str(item).strip() for item in evidence):
            raise ValueError("Evidências devem ser fornecidas como uma lista de registros não vazios.")
        minimum = {"identified": 0, "studied": 1, "experimented": 2,
                   "operational": 2, "specialized": 3, "improver": 4}[competence]
        if len(evidence) < minimum:
            raise ValueError(f"O nível {competence} exige pelo menos {minimum} evidências registradas.")
        with self._transaction() as db:
            row = db.execute("SELECT evidence_json,competence FROM tools WHERE tool_id=?", (tool_id,)).fetchone()
            if not row:
                raise KeyError(f"Ferramenta não cadastrada: {tool_id}")
            order = {name: index for index, name in enumerate(allowed)}
            if order[competence] < order[row["competence"]]:
                raise ValueError("O nível de domínio não pode regredir sem uma revisão explícita.")
            merged = json.loads(row["evidence_json"]) + [str(x) for x in evidence]
            db.execute("UPDATE tools SET competence=?, evidence_json=?, updated_at=? WHERE tool_id=?",
                       (competence, _json(merged), utc_now(), tool_id))

    def list_tools(self) -> list[dict]:
        with self._reader() as db:
            rows = db.execute("SELECT * FROM tools ORDER BY name COLLATE NOCASE").fetchall()
        return [{"tool_id": r["tool_id"], "name": r["name"], "executable_path": r["executable_path"],
                 "version": r["version"], "source": r["source"], "competence": r["competence"],
                 "evidence": json.loads(r["evidence_json"]), "limitations": json.loads(r["limitations_json"]),
                 "metadata": json.loads(r["metadata_json"]), "updated_at": r["updated_at"]} for r in rows]

    def record_installation(self, installation_id: str, name: str, version: str | None,
                            method: str, source_url: str | None, source_ref: str | None,
                            installed_at: str | None, purpose: str,
                            verification: str = "not_verified", license: str | None = None,
                            notes: dict | None = None) -> bool:
        if not installation_id or not name or not method or not purpose:
            raise ValueError("Registro de instalação incompleto.")
        with self._transaction() as db:
            cursor = db.execute("""INSERT OR IGNORE INTO installations(
                installation_id,name,version,method,source_url,source_ref,installed_at,
                purpose,verification,license,notes_json,recorded_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (installation_id, name, version, method, source_url, source_ref,
                 installed_at, purpose, verification, license, _json(notes or {}), utc_now()))
            return cursor.rowcount == 1

    def list_installations(self) -> list[dict]:
        with self._reader() as db:
            rows = db.execute("SELECT * FROM installations ORDER BY name COLLATE NOCASE, recorded_at").fetchall()
        return [{"installation_id": r["installation_id"], "name": r["name"],
                 "version": r["version"], "method": r["method"], "source_url": r["source_url"],
                 "source_ref": r["source_ref"], "installed_at": r["installed_at"],
                 "purpose": r["purpose"], "verification": r["verification"],
                 "license": r["license"], "notes": json.loads(r["notes_json"]),
                 "recorded_at": r["recorded_at"]} for r in rows]

    def save_self_model(self, model: dict) -> int:
        with self._transaction() as db:
            cursor = db.execute("INSERT INTO self_models(model_json,created_at) VALUES(?,?)", (_json(model), utc_now()))
            return int(cursor.lastrowid)

    def latest_self_model(self) -> dict | None:
        with self._reader() as db:
            row = db.execute("SELECT model_json,created_at FROM self_models ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        model = json.loads(row["model_json"])
        model["recorded_at"] = row["created_at"]
        return model

    def import_legacy_file(self, path: str | Path, kind: str) -> dict:
        source = Path(path)
        if not source.is_file():
            return {"status": "not_found", "count": 0}
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        source_path = str(source.resolve())
        source_key = f"legacy:{kind}:{source.name}"
        data = json.loads(raw.decode("utf-8"))
        now = utc_now()
        count = 0
        with self._transaction() as db:
            prior = db.execute("SELECT sha256,imported_count FROM legacy_imports WHERE source_path=?",
                               (source_key,)).fetchone()
            if prior:
                return {"status": "already_imported", "count": prior["imported_count"],
                        "same_content": prior["sha256"] == digest}
            if kind == "memory":
                if not isinstance(data, dict):
                    raise ValueError("Formato legado de memória inválido.")
                for key, item in data.items():
                    value = item.get("value") if isinstance(item, dict) and "value" in item else item
                    legacy_updated = item.get("updated_at") if isinstance(item, dict) else None
                    metadata = {"legacy_source": source_key, "legacy_source_path": source_path,
                                "legacy_updated_at": legacy_updated}
                    db.execute("""INSERT INTO memories(key,value_json,metadata_json,created_at,updated_at)
                        VALUES(?,?,?,?,?) ON CONFLICT(key) DO NOTHING""",
                        (str(key), _json(value), _json(metadata), now, str(legacy_updated or now)))
                    count += 1
            elif kind == "experiments":
                if not isinstance(data, list):
                    raise ValueError("Formato legado de experimentos inválido.")
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    db.execute("""INSERT INTO experiments(hypothesis,method,result,conclusion,
                        metadata_json,created_at) VALUES(?,?,?,?,?,?)""",
                        (str(item.get("hypothesis", "Sem hipótese")),
                         str(item.get("method", "Método legado")),
                         str(item.get("result", "Sem resultado")),
                         str(item.get("conclusion", "Sem conclusão")),
                         _json({"legacy_source": source_key}), str(item.get("date") or now)))
                    count += 1
            else:
                raise ValueError(f"Tipo de importação não suportado: {kind}")
            db.execute("INSERT INTO legacy_imports(source_path,sha256,imported_count,imported_at) VALUES(?,?,?,?)",
                       (source_key, digest, count, now))
            db.execute("INSERT INTO events(event_type,severity,payload_json,created_at) VALUES(?,?,?,?)",
                       ("legacy.imported", "info", _json({"source": source_key, "source_path": source_path,
                         "kind": kind, "count": count}), now))
        return {"status": "imported", "count": count, "sha256": digest}

    def counts(self) -> dict[str, int]:
        tables = (
            "memories", "events", "observations", "experiments",
            "tools", "self_models", "installations",
            "lab_experiments", "lab_experiment_events",
        )
        with self._reader() as db:
            result = {
                table: int(db.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0])
                for table in tables
            }

            existing = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

            result["documents"] = (
                int(db.execute(
                    "SELECT COUNT(*) FROM knowledge_documents"
                ).fetchone()[0])
                if "knowledge_documents" in existing else 0
            )
            result["chunks"] = (
                int(db.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks"
                ).fetchone()[0])
                if "knowledge_chunks" in existing else 0
            )
            result["subjects"] = (
                int(db.execute(
                    "SELECT COUNT(DISTINCT subject) FROM knowledge_documents"
                ).fetchone()[0])
                if "knowledge_documents" in existing else 0
            )
            return result

    def integrity_check(self) -> str:
        with self._reader() as db:
            return str(db.execute("PRAGMA integrity_check").fetchone()[0])

    def checkpoint(self) -> None:
        with self._reader() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
