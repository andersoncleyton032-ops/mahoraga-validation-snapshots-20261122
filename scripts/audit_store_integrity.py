"""Read-only SQLite integrity audit for a Mahoraga Store copy.

The database path is mandatory. The connection is opened in SQLite read-only
mode and query_only is enabled; this tool never initializes or migrates a DB.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def audit_database(path: str | Path, *, batch_size: int = 256) -> dict[str, Any]:
    supplied_path = Path(path).expanduser()
    if supplied_path.is_symlink():
        raise ValueError("O caminho do banco não pode ser link simbólico.")
    database = supplied_path.resolve(strict=True)
    if not database.is_file():
        raise ValueError("O caminho precisa apontar para um arquivo SQLite existente.")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 4096:
        raise ValueError("batch_size deve ser inteiro entre 1 e 4096.")

    uri = database.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()[0] == 1
        quick_check = [row[0] for row in connection.execute("PRAGMA quick_check")]
        foreign_key_violations = [
            {
                "table": row[0],
                "rowid": row[1],
                "parent": row[2],
                "fkid": row[3],
            }
            for row in connection.execute("PRAGMA foreign_key_check")
        ]

        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        json_columns: list[tuple[str, str]] = []
        for table in tables:
            columns = connection.execute(
                f"PRAGMA table_info({_identifier(table)})"
            ).fetchall()
            for column in columns:
                name = str(column["name"])
                if name.endswith("_json") or name in {
                    "payload_json", "value_json", "model_json"
                }:
                    json_columns.append((table, name))

        malformed: list[dict[str, Any]] = []
        malformed_count = 0
        checked_values = 0
        for table, column in json_columns:
            query = (
                f"SELECT rowid AS audit_rowid, {_identifier(column)} AS audit_value "
                f"FROM {_identifier(table)} "
                f"WHERE {_identifier(column)} IS NOT NULL ORDER BY rowid"
            )
            cursor = connection.execute(query)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    checked_values += 1
                    try:
                        json.loads(row["audit_value"])
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        malformed_count += 1
                        if len(malformed) < 100:
                            malformed.append({
                                "table": table,
                                "column": column,
                                "rowid": row["audit_rowid"],
                                "error": type(exc).__name__,
                            })

        migration_rows = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() if "schema_migrations" in tables else []
        migration_versions = [int(row[0]) for row in migration_rows]
        passed = (
            query_only
            and quick_check == ["ok"]
            and not foreign_key_violations
            and not malformed
        )
        return {
            "schema": "mahoraga.sqlite_readonly_audit",
            "schema_version": 1,
            "database": str(database),
            "read_only": True,
            "query_only": query_only,
            "passed": passed,
            "quick_check": quick_check,
            "foreign_key_violation_count": len(foreign_key_violations),
            "foreign_key_violations": foreign_key_violations[:100],
            "table_count": len(tables),
            "tables": tables,
            "json_column_count": len(json_columns),
            "json_values_checked": checked_values,
            "malformed_json_count": malformed_count,
            "malformed_json": malformed,
            "schema_migration_versions": migration_versions,
            "persistent_write_performed": False,
            "schema_migration_performed": False,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Cópia existente do arquivo SQLite")
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()
    try:
        report = audit_database(args.database, batch_size=args.batch_size)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({
            "schema": "mahoraga.sqlite_readonly_audit",
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
