import json
import sqlite3

import pytest

from scripts.audit_store_integrity import audit_database


def _database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE parent (
            id INTEGER PRIMARY KEY
        );
        CREATE TABLE child (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES parent(id),
            metadata_json TEXT
        );
        INSERT INTO schema_migrations VALUES (1);
        INSERT INTO events VALUES (1, '{"ok": true}');
        INSERT INTO parent VALUES (1);
        INSERT INTO child VALUES (1, 1, '{"source": "fixture"}');
        """
    )
    connection.commit()
    connection.close()


def test_readonly_audit_accepts_valid_store_without_writing(tmp_path):
    path = tmp_path / "valid.sqlite3"
    _database(path)
    before = path.read_bytes()

    report = audit_database(path)

    assert report["passed"] is True
    assert report["read_only"] is True
    assert report["query_only"] is True
    assert report["quick_check"] == ["ok"]
    assert report["json_values_checked"] == 2
    assert report["persistent_write_performed"] is False
    assert path.read_bytes() == before


def test_readonly_audit_reports_malformed_json_by_table_column_and_row(tmp_path):
    path = tmp_path / "malformed.sqlite3"
    _database(path)
    connection = sqlite3.connect(path)
    connection.execute("INSERT INTO events VALUES (2, '{broken')")
    connection.commit()
    connection.close()

    report = audit_database(path)

    assert report["passed"] is False
    assert report["malformed_json_count"] == 1
    assert report["malformed_json"][0]["table"] == "events"
    assert report["malformed_json"][0]["column"] == "payload_json"
    assert report["malformed_json"][0]["rowid"] == 2


def test_readonly_audit_detects_foreign_key_violations(tmp_path):
    path = tmp_path / "foreign-key.sqlite3"
    _database(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("INSERT INTO child VALUES (2, 999, '{}')")
    connection.commit()
    connection.close()

    report = audit_database(path)

    assert report["passed"] is False
    assert report["foreign_key_violation_count"] == 1
    assert report["foreign_key_violations"][0]["table"] == "child"


def test_readonly_audit_requires_existing_database_and_bounded_batch(tmp_path):
    with pytest.raises(FileNotFoundError):
        audit_database(tmp_path / "missing.sqlite3")
    path = tmp_path / "valid.sqlite3"
    _database(path)
    with pytest.raises(ValueError, match="batch_size"):
        audit_database(path, batch_size=True)



def test_readonly_audit_counts_all_corrupt_rows_but_bounds_details(tmp_path):
    path = tmp_path / "many-malformed.sqlite3"
    _database(path)
    connection = sqlite3.connect(path)
    connection.executemany(
        "INSERT INTO events VALUES (?, ?)",
        [(index, "{broken") for index in range(2, 107)],
    )
    connection.commit()
    connection.close()

    report = audit_database(path)

    assert report["malformed_json_count"] == 105
    assert len(report["malformed_json"]) == 100


def test_readonly_audit_rejects_symlink_paths(tmp_path):
    path = tmp_path / "valid.sqlite3"
    _database(path)
    link = tmp_path / "alias.sqlite3"
    link.symlink_to(path)

    with pytest.raises(ValueError, match="link simbólico"):
        audit_database(link)
