from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from agent.store import KnowledgeStore
from agent.visual_creation import VisualDocumentSpec, VisualLayerSpec
from agent.visual_document_store import (
    VisualDocumentConflictError,
    VisualDocumentIntegrityError,
    VisualDocumentStore,
    VisualDocumentStoreError,
)


def sample_document() -> VisualDocumentSpec:
    return VisualDocumentSpec(
        document_id="scene.persist.001",
        title="Estudo persistente",
        coordinate_space="2d",
        canvas_width=640,
        canvas_height=480,
        layers=(VisualLayerSpec("layer.main", "Main", 0),),
    )


def test_visual_document_store_saves_and_loads_exact_immutable_document(tmp_path):
    database = KnowledgeStore(tmp_path / "mahoraga.sqlite3")
    store = VisualDocumentStore(database)
    document = sample_document()

    saved = store.save(document)
    reopened = VisualDocumentStore(database.db_path)
    loaded = reopened.get(document.document_id)

    assert saved.status == "created"
    assert saved.revision == 1
    assert saved.sha256 == document.sha256()
    assert saved.parent_sha256 is None
    assert loaded is not None
    assert loaded.status == "loaded"
    assert loaded.document.to_json() == document.to_json()
    assert loaded.sha256 == document.sha256()
    assert store.db_path == database.db_path.resolve()


def test_visual_document_store_duplicate_save_is_idempotent(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")
    document = sample_document()

    first = store.save(document)
    duplicate = store.save(document)

    assert first.revision == duplicate.revision == 1
    assert first.sha256 == duplicate.sha256
    assert duplicate.status == "duplicate"
    assert len(store.list_revisions(document.document_id)) == 1


def test_visual_document_store_appends_revision_with_compare_and_set(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")
    first_document = sample_document()
    first = store.save(first_document)
    second_document = replace(first_document, title="Estudo revisado")

    second = store.save(
        second_document,
        expected_parent_sha256=first.sha256,
    )

    assert second.status == "updated"
    assert second.revision == 2
    assert second.parent_sha256 == first.sha256
    assert second.sha256 == second_document.sha256()
    assert store.get(first_document.document_id, revision=1).document.to_json() == (
        first_document.to_json()
    )
    assert store.get(first_document.document_id, revision=2).document.to_json() == (
        second_document.to_json()
    )
    assert [item["revision"] for item in store.list_revisions(first_document.document_id)] == [1, 2]


def test_visual_document_store_rejects_stale_or_missing_parent_revision(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")
    document = sample_document()
    first = store.save(document)
    edited = replace(document, title="Edição concorrente")

    with pytest.raises(VisualDocumentConflictError, match="expected_parent_sha256"):
        store.save(edited, expected_parent_sha256="0" * 64)

    with pytest.raises(VisualDocumentConflictError, match="expected_parent_sha256"):
        store.save(edited)

    assert len(store.list_revisions(document.document_id)) == 1
    assert store.get(document.document_id).sha256 == first.sha256


def test_visual_document_store_rejects_parent_for_initial_revision(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")

    with pytest.raises(VisualDocumentConflictError, match="a revisão inicial"):
        store.save(sample_document(), expected_parent_sha256="1" * 64)


def test_visual_document_store_detects_tampered_persisted_content(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")
    document = sample_document()
    saved = store.save(document)
    db = sqlite3.connect(str(store.db_path))
    try:
        db.execute(
            "UPDATE visual_document_revisions SET content_json=? WHERE document_id=? AND revision=1",
            (document.to_json().replace("Estudo persistente", "Conteúdo alterado"), document.document_id),
        )
        db.commit()
    finally:
        db.close()

    with pytest.raises(VisualDocumentIntegrityError, match="SHA-256"):
        store.get(document.document_id)


def test_visual_document_store_rejects_non_visual_document(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")

    with pytest.raises(TypeError, match="VisualDocumentSpec"):
        store.save({"document_id": "not-a-document"})


def test_visual_document_store_missing_document_returns_none(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")

    assert store.get("scene.missing") is None
    assert store.list_revisions("scene.missing") == ()


def test_visual_document_store_compare_and_set_allows_only_one_concurrent_writer(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")
    initial = store.save(sample_document())
    candidates = [
        replace(initial.document, title="Concorrente A"),
        replace(initial.document, title="Concorrente B"),
    ]

    def write(candidate):
        try:
            return store.save(candidate, expected_parent_sha256=initial.sha256)
        except VisualDocumentConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, candidates))

    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, VisualDocumentConflictError) for item in results) == 1
    assert len(store.list_revisions(initial.document.document_id)) == 2


def test_visual_document_store_budget_is_configurable(tmp_path):
    document = sample_document()
    store = VisualDocumentStore(
        tmp_path / "bounded.sqlite3",
        max_document_bytes=1,
    )

    with pytest.raises(VisualDocumentStoreError, match="orçamento configurado"):
        store.save(document)

    unbounded = VisualDocumentStore(
        tmp_path / "unbounded.sqlite3",
        max_document_bytes=None,
    )
    assert unbounded.save(document).status == "created"


def test_visual_document_store_rejects_invalid_budget(tmp_path):
    with pytest.raises(ValueError, match="max_document_bytes"):
        VisualDocumentStore(tmp_path / "invalid.sqlite3", max_document_bytes=True)


def test_visual_document_store_can_revert_to_prior_content_as_new_revision(tmp_path):
    store = VisualDocumentStore(tmp_path / "mahoraga.sqlite3")
    original = sample_document()
    first = store.save(original)
    edited = replace(original, title="Versão intermediária")
    second = store.save(edited, expected_parent_sha256=first.sha256)

    reverted = store.save(original, expected_parent_sha256=second.sha256)

    assert reverted.status == "updated"
    assert reverted.revision == 3
    assert reverted.sha256 == first.sha256
    assert reverted.parent_sha256 == second.sha256
    assert store.get(original.document_id).revision == 3
    assert store.get(original.document_id, revision=3).document.to_json() == original.to_json()


def test_visual_document_store_migrates_legacy_unique_digest_schema(tmp_path):
    import hashlib

    database_path = tmp_path / "legacy.sqlite3"
    first = sample_document()
    second = replace(first, title="Versão legada dois")
    db = sqlite3.connect(str(database_path))
    try:
        db.execute(
            """
            CREATE TABLE visual_document_revisions (
                document_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision > 0),
                schema TEXT NOT NULL,
                sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
                parent_sha256 TEXT,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(document_id, revision),
                UNIQUE(document_id, sha256)
            )
            """
        )
        db.execute(
            """
            INSERT INTO visual_document_revisions
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first.document_id, 1, "mahoraga.visual_document.v1",
                hashlib.sha256(first.to_json().encode("utf-8")).hexdigest(),
                None, first.to_json(), "2026-11-25T00:00:00+00:00",
            ),
        )
        db.execute(
            """
            INSERT INTO visual_document_revisions
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                second.document_id, 2, "mahoraga.visual_document.v1",
                hashlib.sha256(second.to_json().encode("utf-8")).hexdigest(),
                hashlib.sha256(first.to_json().encode("utf-8")).hexdigest(),
                second.to_json(), "2026-11-25T00:00:01+00:00",
            ),
        )
        db.commit()
    finally:
        db.close()

    store = VisualDocumentStore(database_path)
    reverted = store.save(
        first,
        expected_parent_sha256=second.sha256(),
    )

    assert reverted.revision == 3
    assert reverted.sha256 == first.sha256()
    assert store.get(first.document_id, revision=1) is not None
    assert store.get(first.document_id, revision=2) is not None
    assert store.get(first.document_id, revision=3) is not None



def test_visual_document_store_migration_rolls_back_schema_rename_on_failure(tmp_path):
    database_path = tmp_path / "interrupted-legacy.sqlite3"
    db = sqlite3.connect(str(database_path))
    try:
        # This legacy shape triggers the migration path but is incomplete.
        # The failed copy must not leave a half-renamed schema behind.
        db.execute(
            """
            CREATE TABLE visual_document_revisions (
                document_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision > 0),
                schema TEXT NOT NULL,
                sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
                parent_sha256 TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY(document_id, revision),
                UNIQUE(document_id, sha256)
            )
            """
        )
        db.commit()
    finally:
        db.close()

    with pytest.raises(sqlite3.OperationalError, match="content_json"):
        VisualDocumentStore(database_path)

    check = sqlite3.connect(str(database_path))
    try:
        tables = {
            row[0]
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        check.close()

    assert "visual_document_revisions" in tables
    assert "visual_document_revisions_legacy_v1" not in tables


@pytest.mark.parametrize("legacy_unique_form", ["quoted_constraint", "separate_index", "reversed_index", "partial_index"])
def test_visual_document_store_migrates_legacy_unique_digest_variants(
    tmp_path, legacy_unique_form,
):
    import hashlib

    database_path = tmp_path / f"legacy-{legacy_unique_form}.sqlite3"
    first = sample_document()
    second = replace(first, title="Versão legada dois")
    db = sqlite3.connect(str(database_path))
    try:
        unique_clause = (
            'UNIQUE("document_id", "sha256")'
            if legacy_unique_form == "quoted_constraint"
            else ""
        )
        db.execute(
            f"""
            CREATE TABLE visual_document_revisions (
                document_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision > 0),
                schema TEXT NOT NULL,
                sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
                parent_sha256 TEXT,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(document_id, revision)
                {"," if unique_clause else ""} {unique_clause}
            )
            """
        )
        if legacy_unique_form in {"separate_index", "reversed_index", "partial_index"}:
            indexed_columns = (
                "sha256, document_id"
                if legacy_unique_form == "reversed_index"
                else "document_id, sha256"
            )
            partial_predicate = " WHERE revision > 0" if legacy_unique_form == "partial_index" else ""
            db.execute(
                "CREATE UNIQUE INDEX legacy_document_digest_uq "
                f"ON visual_document_revisions ({indexed_columns}){partial_predicate}"
            )
        for revision, document, parent, created_at in (
            (1, first, None, "2026-11-25T00:00:00+00:00"),
            (2, second, first.sha256(), "2026-11-25T00:00:01+00:00"),
        ):
            db.execute(
                "INSERT INTO visual_document_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    document.document_id,
                    revision,
                    "mahoraga.visual_document.v1",
                    hashlib.sha256(document.to_json().encode("utf-8")).hexdigest(),
                    parent,
                    document.to_json(),
                    created_at,
                ),
            )
        db.commit()
    finally:
        db.close()

    store = VisualDocumentStore(database_path)
    reverted = store.save(first, expected_parent_sha256=second.sha256())

    assert reverted.revision == 3
    assert reverted.sha256 == first.sha256()
    assert store.get(first.document_id, revision=1) is not None
    assert store.get(first.document_id, revision=2) is not None
    assert store.get(first.document_id, revision=3) is not None
