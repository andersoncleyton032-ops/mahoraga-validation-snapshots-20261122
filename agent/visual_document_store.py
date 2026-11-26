"""Append-only persistence for editable visual documents in the shared SQLite store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .visual_creation import VisualDocumentError, VisualDocumentSpec


class VisualDocumentStoreError(RuntimeError):
    """Base error for visual-document persistence."""


class VisualDocumentConflictError(VisualDocumentStoreError):
    """Raised when a save is based on a stale document revision."""


class VisualDocumentIntegrityError(VisualDocumentStoreError):
    """Raised when persisted bytes do not match their declared identity."""


@dataclass(frozen=True)
class StoredVisualDocument:
    document: VisualDocumentSpec
    revision: int
    sha256: str
    parent_sha256: str | None
    created_at: str
    status: str


class VisualDocumentStore:
    """Immutable document revisions sharing Mahoraga's canonical SQLite DB.

    This is a domain-specific repository, not a second memory database. It
    stores only the editable JSON representation; media bytes remain in the
    existing ArtifactStore and are referenced by asset ID.
    """

    SCHEMA = "mahoraga.visual_document.v1"
    MAX_DOCUMENT_BYTES = 4 * 1024 * 1024

    def __init__(
        self,
        store_or_path: Any,
        *,
        max_document_bytes: int | None = MAX_DOCUMENT_BYTES,
    ):
        if max_document_bytes is not None and (
            isinstance(max_document_bytes, bool)
            or not isinstance(max_document_bytes, int)
            or max_document_bytes < 1
        ):
            raise ValueError("max_document_bytes deve ser inteiro positivo ou None.")
        self.max_document_bytes = max_document_bytes
        raw_path = getattr(store_or_path, "db_path", store_or_path)
        if not isinstance(raw_path, (str, Path)):
            raise TypeError("VisualDocumentStore exige KnowledgeStore ou caminho SQLite.")
        self.db_path = Path(raw_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.db_path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _initialize(self) -> None:
        db = self._connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            existing = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                ("visual_document_revisions",),
            ).fetchone()
            if existing is not None:
                normalized_sql = "".join(str(existing["sql"]).upper().split())
                if "UNIQUE(DOCUMENT_ID,SHA256)" in normalized_sql:
                    db.execute(
                        "ALTER TABLE visual_document_revisions "
                        "RENAME TO visual_document_revisions_legacy_v1"
                    )
                    db.execute("DROP INDEX IF EXISTS idx_visual_document_latest")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_document_revisions (
                    document_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    schema TEXT NOT NULL,
                    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
                    parent_sha256 TEXT,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, revision)
                )
                """
            )
            legacy = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                ("visual_document_revisions_legacy_v1",),
            ).fetchone()
            if legacy is not None:
                db.execute(
                    """
                    INSERT INTO visual_document_revisions
                    (document_id, revision, schema, sha256, parent_sha256, content_json, created_at)
                    SELECT document_id, revision, schema, sha256, parent_sha256, content_json, created_at
                    FROM visual_document_revisions_legacy_v1
                    """
                )
                db.execute("DROP TABLE visual_document_revisions_legacy_v1")
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_visual_document_latest
                ON visual_document_revisions(document_id, revision DESC)
                """
            )
            db.commit()
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _record(row: sqlite3.Row, *, status: str) -> StoredVisualDocument:
        if row["schema"] != VisualDocumentStore.SCHEMA:
            raise VisualDocumentIntegrityError("Schema do documento persistido é incompatível.")
        content = row["content_json"]
        if not isinstance(content, str):
            raise VisualDocumentIntegrityError("Conteúdo persistido não é texto.")
        digest = VisualDocumentStore._digest(content)
        if digest != row["sha256"]:
            raise VisualDocumentIntegrityError("SHA-256 do documento persistido não confere.")
        try:
            document = VisualDocumentSpec.from_json(content)
        except (VisualDocumentError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VisualDocumentIntegrityError("Documento visual persistido é inválido.") from exc
        if document.document_id != row["document_id"] or document.sha256() != digest:
            raise VisualDocumentIntegrityError("Identidade do documento persistido não confere.")
        return StoredVisualDocument(
            document=document,
            revision=int(row["revision"]),
            sha256=digest,
            parent_sha256=row["parent_sha256"],
            created_at=row["created_at"],
            status=status,
        )

    def save(
        self,
        document: VisualDocumentSpec,
        *,
        expected_parent_sha256: str | None = None,
    ) -> StoredVisualDocument:
        """Append a revision; existing documents require compare-and-set."""
        if not isinstance(document, VisualDocumentSpec):
            raise TypeError("document deve ser VisualDocumentSpec.")
        content = document.to_json()
        content_bytes = content.encode("utf-8")
        if (
            self.max_document_bytes is not None
            and len(content_bytes) > self.max_document_bytes
        ):
            raise VisualDocumentStoreError("Documento visual excede o orçamento configurado.")
        digest = self._digest(content)
        if digest != document.sha256():
            raise VisualDocumentIntegrityError("Digest serializado diverge do documento em memória.")
        if expected_parent_sha256 is not None and (
            not isinstance(expected_parent_sha256, str)
            or len(expected_parent_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_parent_sha256)
        ):
            raise ValueError("expected_parent_sha256 deve ser SHA-256 hexadecimal ou None.")

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute(
                """
                SELECT revision, sha256 FROM visual_document_revisions
                WHERE document_id=? ORDER BY revision DESC LIMIT 1
                """,
                (document.document_id,),
            ).fetchone()
            if latest is not None and latest["sha256"] == digest:
                current = db.execute(
                    """
                    SELECT * FROM visual_document_revisions
                    WHERE document_id=? AND revision=?
                    """,
                    (document.document_id, latest["revision"]),
                ).fetchone()
                db.commit()
                return self._record(current, status="duplicate")
            if latest is None:
                if expected_parent_sha256 is not None:
                    raise VisualDocumentConflictError(
                        "Documento ainda não existe; a revisão inicial não aceita parent SHA."
                    )
                revision = 1
                parent_sha256 = None
                status = "created"
            else:
                if expected_parent_sha256 != latest["sha256"]:
                    raise VisualDocumentConflictError(
                        "Revisão desatualizada: expected_parent_sha256 não corresponde à última versão."
                    )
                revision = int(latest["revision"]) + 1
                parent_sha256 = latest["sha256"]
                status = "updated"

            created_at = self._now()
            db.execute(
                """
                INSERT INTO visual_document_revisions
                (document_id, revision, schema, sha256, parent_sha256, content_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id, revision, self.SCHEMA, digest,
                    parent_sha256, content, created_at,
                ),
            )
            db.commit()
            return StoredVisualDocument(
                document=document,
                revision=revision,
                sha256=digest,
                parent_sha256=parent_sha256,
                created_at=created_at,
                status=status,
            )
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def get(
        self,
        document_id: str,
        *,
        revision: int | None = None,
    ) -> StoredVisualDocument | None:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id deve ser texto não vazio.")
        if revision is not None and (
            isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
        ):
            raise ValueError("revision deve ser inteiro positivo ou None.")
        db = self._connect()
        try:
            if revision is None:
                row = db.execute(
                    """
                    SELECT * FROM visual_document_revisions
                    WHERE document_id=? ORDER BY revision DESC LIMIT 1
                    """,
                    (document_id,),
                ).fetchone()
            else:
                row = db.execute(
                    """
                    SELECT * FROM visual_document_revisions
                    WHERE document_id=? AND revision=?
                    """,
                    (document_id, revision),
                ).fetchone()
            return self._record(row, status="loaded") if row is not None else None
        finally:
            db.close()

    def list_revisions(self, document_id: str) -> tuple[dict[str, Any], ...]:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id deve ser texto não vazio.")
        db = self._connect()
        try:
            rows = db.execute(
                """
                SELECT document_id, revision, sha256, parent_sha256, created_at
                FROM visual_document_revisions
                WHERE document_id=? ORDER BY revision ASC
                """,
                (document_id,),
            ).fetchall()
            return tuple(dict(row) for row in rows)
        finally:
            db.close()
