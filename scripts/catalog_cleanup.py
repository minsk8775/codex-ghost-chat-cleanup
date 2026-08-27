#!/usr/bin/env python3
"""Inspect or remove one confirmed ghost entry from the Codex local catalog."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path


CONFIRM_TOKEN = "DELETE_ONE_CONFIRMED_GHOST"
REQUIRED_COLUMNS = {
    "thread_id",
    "display_title",
    "source_kind",
    "host_id",
    "missing_candidate",
}


class CleanupError(RuntimeError):
    pass


def emit(payload: dict, *, stream=sys.stdout) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True), file=stream)


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def resolve_db(raw_path: str | None) -> Path:
    path = (
        Path(raw_path).expanduser()
        if raw_path
        else Path.home() / ".codex" / "sqlite" / "codex-dev.db"
    ).resolve()
    if not path.is_file():
        raise CleanupError(f"live database not found: {path}")
    return path


def connect(path: Path, mode: str) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def validate_schema(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_thread_catalog'"
    ).fetchone()
    if table is None:
        raise CleanupError("local_thread_catalog table is missing")
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(local_thread_catalog)")
    }
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise CleanupError(f"unsupported catalog schema; missing columns: {missing}")


def quick_check(connection: sqlite3.Connection) -> str:
    result = connection.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise CleanupError(f"database quick_check failed: {result}")
    return result


def catalog_rows(
    connection: sqlite3.Connection, thread_id: str | None = None
) -> list[dict]:
    sql = """
        SELECT thread_id, display_title, source_kind, host_id,
               missing_candidate, source_created_at, source_updated_at
        FROM local_thread_catalog
    """
    parameters: tuple[str, ...] = ()
    if thread_id:
        sql += " WHERE thread_id = ?"
        parameters = (thread_id,)
    sql += " ORDER BY source_recency_at DESC"
    return [dict(row) for row in connection.execute(sql, parameters)]


def find_other_references(
    connection: sqlite3.Connection, thread_id: str
) -> list[dict]:
    references: list[dict] = []
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        if table == "local_thread_catalog":
            continue
        columns = {
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({quote_identifier(table)})"
            )
        }
        if "thread_id" not in columns:
            continue
        count = connection.execute(
            f"SELECT COUNT(*) FROM {quote_identifier(table)} WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()[0]
        if count:
            references.append({"table": table, "count": count})
    return references


def inspect_database(args: argparse.Namespace) -> None:
    database = resolve_db(args.db)
    with connect(database, "ro") as connection:
        validate_schema(connection)
        integrity = quick_check(connection)
        total = connection.execute(
            "SELECT COUNT(*) FROM local_thread_catalog"
        ).fetchone()[0]
        missing_candidates = connection.execute(
            "SELECT COUNT(*) FROM local_thread_catalog WHERE missing_candidate = 1"
        ).fetchone()[0]
        rows = catalog_rows(connection, args.thread_id)
        references = (
            find_other_references(connection, args.thread_id)
            if args.thread_id
            else []
        )
    emit(
        {
            "catalog_total": total,
            "database": str(database),
            "integrity": integrity,
            "missing_candidates": missing_candidates,
            "other_references": references,
            "rows": rows,
        }
    )


def backup_database(database: Path, backup_dir: Path) -> Path:
    backup_dir = backup_dir.expanduser().resolve()
    if backup_dir == database.parent.resolve():
        raise CleanupError("backup directory must not be the live database directory")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = backup_dir / f"codex-dev-pre-ghost-cleanup-{stamp}.sqlite"
    source = connect(database, "ro")
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup


def delete_entry(args: argparse.Namespace) -> None:
    if args.confirm != CONFIRM_TOKEN:
        raise CleanupError("explicit deletion confirmation token is required")

    database = resolve_db(args.db)
    expected_title = args.expected_title
    expected_source_kind = args.expected_source_kind

    with connect(database, "ro") as connection:
        validate_schema(connection)
        quick_check(connection)
        rows = catalog_rows(connection, args.thread_id)
        if len(rows) != 1:
            raise CleanupError(f"target row count must be 1, found {len(rows)}")
        target = rows[0]
        if target["display_title"] != expected_title:
            raise CleanupError("target title does not match exactly")
        if target["source_kind"] != expected_source_kind:
            raise CleanupError("target source kind does not match exactly")
        references = find_other_references(connection, args.thread_id)
        if references:
            raise CleanupError(f"target is referenced by other tables: {references}")

    backup = backup_database(database, Path(args.backup_dir))

    connection = connect(database, "rw")
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        before = connection.execute(
            "SELECT COUNT(*) FROM local_thread_catalog"
        ).fetchone()[0]
        row = connection.execute(
            """
            SELECT display_title, source_kind
            FROM local_thread_catalog
            WHERE thread_id = ?
            """,
            (args.thread_id,),
        ).fetchall()
        if len(row) != 1:
            raise CleanupError("target changed before deletion")
        if row[0]["display_title"] != expected_title:
            raise CleanupError("target title changed before deletion")
        if row[0]["source_kind"] != expected_source_kind:
            raise CleanupError("target source kind changed before deletion")

        cursor = connection.execute(
            """
            DELETE FROM local_thread_catalog
            WHERE thread_id = ? AND display_title = ? AND source_kind = ?
            """,
            (args.thread_id, expected_title, expected_source_kind),
        )
        if cursor.rowcount != 1:
            raise CleanupError(f"delete count must be 1, found {cursor.rowcount}")

        metadata_exists = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='local_thread_catalog_metadata'
            """
        ).fetchone()
        if metadata_exists:
            connection.execute(
                """
                UPDATE local_thread_catalog_metadata
                SET catalog_revision = catalog_revision + 1
                WHERE id = 1
                """
            )
        connection.commit()

        remaining = connection.execute(
            "SELECT COUNT(*) FROM local_thread_catalog WHERE thread_id = ?",
            (args.thread_id,),
        ).fetchone()[0]
        after = connection.execute(
            "SELECT COUNT(*) FROM local_thread_catalog"
        ).fetchone()[0]
        integrity = quick_check(connection)
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

    emit(
        {
            "backup": str(backup),
            "catalog_after": after,
            "catalog_before": before,
            "deleted": 1,
            "integrity": integrity,
            "target_remaining": remaining,
            "thread_id": args.thread_id,
            "title": expected_title,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or remove one confirmed Codex ghost-chat catalog entry."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Read catalog state only")
    inspect_parser.add_argument("--db", help="Absolute live Codex database path")
    inspect_parser.add_argument("--thread-id", help="Inspect one exact thread ID")
    inspect_parser.set_defaults(handler=inspect_database)

    delete_parser = subparsers.add_parser(
        "delete", help="Back up the database and delete one verified catalog row"
    )
    delete_parser.add_argument("--db", help="Absolute live Codex database path")
    delete_parser.add_argument("--thread-id", required=True)
    delete_parser.add_argument("--expected-title", required=True)
    delete_parser.add_argument("--expected-source-kind", default="chatgpt")
    delete_parser.add_argument("--backup-dir", required=True)
    delete_parser.add_argument("--confirm", required=True)
    delete_parser.set_defaults(handler=delete_entry)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
        return 0
    except (CleanupError, sqlite3.Error, OSError) as error:
        emit({"error": str(error), "type": type(error).__name__}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
