#!/usr/bin/env python3
"""Inspect or remove a user-confirmed ghost batch from the Codex local catalog."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


CONFIRM_ONE_TOKEN = "DELETE_ONE_CONFIRMED_GHOST"
CONFIRM_BATCH_TOKEN = "DELETE_CONFIRMED_GHOST_BATCH"
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
    with closing(connect(database, "ro")) as connection:
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


def display_target(target: dict) -> str:
    title = target["expected_title"] or "[제목 없음]"
    return f"{title} ({target['thread_id']})"


def validate_targets(raw_targets: object) -> list[dict]:
    if not isinstance(raw_targets, list) or not raw_targets:
        raise CleanupError("manifest targets must be a non-empty list")

    targets: list[dict] = []
    seen_ids: set[str] = set()
    for index, raw_target in enumerate(raw_targets, start=1):
        if not isinstance(raw_target, dict):
            raise CleanupError(f"manifest target {index} must be an object")

        thread_id = raw_target.get("thread_id")
        expected_title = raw_target.get("expected_title")
        expected_source_kind = raw_target.get("expected_source_kind", "chatgpt")
        if not isinstance(thread_id, str) or not thread_id:
            raise CleanupError(f"manifest target {index} has an invalid thread_id")
        if not isinstance(expected_title, str):
            raise CleanupError(f"manifest target {index} has an invalid expected_title")
        if not isinstance(expected_source_kind, str) or not expected_source_kind:
            raise CleanupError(
                f"manifest target {index} has an invalid expected_source_kind"
            )
        if thread_id in seen_ids:
            raise CleanupError(f"duplicate thread_id in manifest: {thread_id}")
        seen_ids.add(thread_id)
        targets.append(
            {
                "thread_id": thread_id,
                "expected_title": expected_title,
                "expected_source_kind": expected_source_kind,
            }
        )
    return targets


def load_batch_manifest(raw_path: str) -> tuple[Path, list[dict]]:
    manifest = Path(raw_path).expanduser().resolve()
    if not manifest.is_file():
        raise CleanupError(f"batch manifest not found: {manifest}")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CleanupError(f"invalid batch manifest: {error}") from error
    if not isinstance(payload, dict):
        raise CleanupError("batch manifest root must be an object")
    return manifest, validate_targets(payload.get("targets"))


def preflight_targets(
    connection: sqlite3.Connection, targets: list[dict]
) -> list[dict]:
    validated: list[dict] = []
    for target in targets:
        rows = catalog_rows(connection, target["thread_id"])
        if len(rows) != 1:
            raise CleanupError(
                f"target row count must be 1 for {display_target(target)}, found {len(rows)}"
            )
        row = rows[0]
        if row["display_title"] != target["expected_title"]:
            raise CleanupError(f"target title does not match: {display_target(target)}")
        if row["source_kind"] != target["expected_source_kind"]:
            raise CleanupError(
                f"target source kind does not match: {display_target(target)}"
            )
        references = find_other_references(connection, target["thread_id"])
        if references:
            raise CleanupError(
                f"target is referenced by other tables: {display_target(target)} {references}"
            )
        validated.append(row)
    return validated


def backup_database(database: Path, backup_dir: Path, *, batch: bool) -> Path:
    backup_dir = backup_dir.expanduser().resolve()
    if backup_dir == database.parent.resolve():
        raise CleanupError("backup directory must not be the live database directory")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    label = "ghost-cleanup-batch" if batch else "ghost-cleanup"
    backup = backup_dir / f"codex-dev-pre-{label}-{stamp}.sqlite"
    source = connect(database, "ro")
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
        quick_check(destination)
    finally:
        destination.close()
        source.close()
    return backup


def delete_targets(
    *, database: Path, targets: list[dict], backup_dir: Path, batch: bool
) -> dict:
    with closing(connect(database, "ro")) as connection:
        validate_schema(connection)
        quick_check(connection)
        preflight_targets(connection, targets)

    backup = backup_database(database, backup_dir, batch=batch)

    connection = connect(database, "rw")
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        validate_schema(connection)
        quick_check(connection)
        connection.execute("BEGIN IMMEDIATE")
        preflight_targets(connection, targets)
        before = connection.execute(
            "SELECT COUNT(*) FROM local_thread_catalog"
        ).fetchone()[0]

        deleted = 0
        for target in targets:
            cursor = connection.execute(
                """
                DELETE FROM local_thread_catalog
                WHERE thread_id = ? AND display_title = ? AND source_kind = ?
                """,
                (
                    target["thread_id"],
                    target["expected_title"],
                    target["expected_source_kind"],
                ),
            )
            if cursor.rowcount != 1:
                raise CleanupError(
                    f"delete count must be 1 for {display_target(target)}, found {cursor.rowcount}"
                )
            deleted += cursor.rowcount

        if deleted != len(targets):
            raise CleanupError(
                f"batch delete count must be {len(targets)}, found {deleted}"
            )

        remaining = sum(
            connection.execute(
                "SELECT COUNT(*) FROM local_thread_catalog WHERE thread_id = ?",
                (target["thread_id"],),
            ).fetchone()[0]
            for target in targets
        )
        if remaining != 0:
            raise CleanupError(f"confirmed targets remaining before commit: {remaining}")

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

        quick_check(connection)
        connection.commit()
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

    return {
        "backup": str(backup),
        "catalog_after": after,
        "catalog_before": before,
        "deleted": deleted,
        "integrity": integrity,
        "target_remaining": remaining,
        "targets": [
            {
                "display": display_target(target),
                "source_kind": target["expected_source_kind"],
                "thread_id": target["thread_id"],
                "title": target["expected_title"],
            }
            for target in targets
        ],
    }


def delete_entry(args: argparse.Namespace) -> None:
    if args.confirm != CONFIRM_ONE_TOKEN:
        raise CleanupError("explicit single-deletion confirmation token is required")
    target = {
        "thread_id": args.thread_id,
        "expected_title": args.expected_title,
        "expected_source_kind": args.expected_source_kind,
    }
    result = delete_targets(
        database=resolve_db(args.db),
        targets=validate_targets([target]),
        backup_dir=Path(args.backup_dir),
        batch=False,
    )
    emit(result)


def delete_batch(args: argparse.Namespace) -> None:
    if args.confirm != CONFIRM_BATCH_TOKEN:
        raise CleanupError("explicit batch-deletion confirmation token is required")
    manifest, targets = load_batch_manifest(args.manifest)
    result = delete_targets(
        database=resolve_db(args.db),
        targets=targets,
        backup_dir=Path(args.backup_dir),
        batch=True,
    )
    result["manifest"] = str(manifest)
    emit(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or remove user-confirmed Codex ghost-chat catalog entries."
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

    batch_parser = subparsers.add_parser(
        "delete-batch",
        help="Back up the database and atomically delete a confirmed manifest",
    )
    batch_parser.add_argument("--db", help="Absolute live Codex database path")
    batch_parser.add_argument("--manifest", required=True)
    batch_parser.add_argument("--backup-dir", required=True)
    batch_parser.add_argument("--confirm", required=True)
    batch_parser.set_defaults(handler=delete_batch)
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
