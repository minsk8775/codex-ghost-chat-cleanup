from __future__ import annotations

import json
import importlib.util
import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "catalog_cleanup.py"
SPEC = importlib.util.spec_from_file_location("catalog_cleanup", SCRIPT)
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


class CatalogCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "codex-dev.db"
        self.backups = self.root / "backups"
        self.manifest = self.root / "confirmed.json"
        self._create_database()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create_database(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(
                """
                CREATE TABLE local_thread_catalog (
                    thread_id TEXT PRIMARY KEY,
                    display_title TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    host_id TEXT,
                    missing_candidate INTEGER NOT NULL,
                    source_created_at TEXT,
                    source_updated_at TEXT,
                    source_recency_at INTEGER NOT NULL
                );
                CREATE TABLE local_thread_catalog_metadata (
                    id INTEGER PRIMARY KEY,
                    catalog_revision INTEGER NOT NULL
                );
                INSERT INTO local_thread_catalog_metadata VALUES (1, 10);
                """
            )
            connection.executemany(
                """
                INSERT INTO local_thread_catalog (
                    thread_id, display_title, source_kind, host_id,
                    missing_candidate, source_created_at, source_updated_at,
                    source_recency_at
                ) VALUES (?, ?, 'chatgpt', 'local', 1, NULL, NULL, ?)
                """,
                [
                    ("thread-alpha", "Alpha ghost", 3),
                    ("thread-beta", "베타 유령", 2),
                    ("thread-keep", "Keep me", 1),
                ],
            )
            connection.commit()

    def _write_manifest(self, targets: list[dict]) -> None:
        self.manifest.write_text(
            json.dumps({"targets": targets}, ensure_ascii=False), encoding="utf-8"
        )

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def _targets(self) -> list[dict]:
        return [
            {
                "thread_id": "thread-alpha",
                "expected_title": "Alpha ghost",
                "expected_source_kind": "chatgpt",
            },
            {
                "thread_id": "thread-beta",
                "expected_title": "베타 유령",
                "expected_source_kind": "chatgpt",
            },
        ]

    def test_batch_delete_is_atomic_and_backup_restores_rows(self) -> None:
        self._write_manifest(self._targets())
        result = self._run(
            "delete-batch",
            "--db",
            str(self.database),
            "--manifest",
            str(self.manifest),
            "--backup-dir",
            str(self.backups),
            "--confirm",
            "DELETE_CONFIRMED_GHOST_BATCH",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["deleted"], 2)
        self.assertEqual(payload["catalog_before"], 3)
        self.assertEqual(payload["catalog_after"], 1)
        self.assertEqual(payload["integrity"], "ok")
        self.assertEqual(payload["transaction_status"], "committed")
        self.assertEqual(payload["postcheck"], "passed")
        self.assertEqual(
            [target["display"] for target in payload["targets"]],
            ["Alpha ghost (thread-alpha)", "베타 유령 (thread-beta)"],
        )

        backup = Path(payload["backup"])
        self.assertTrue(backup.is_file())
        self.assertIn("pre-ghost-cleanup-batch", backup.name)

        with closing(sqlite3.connect(self.database)) as connection:
            remaining = connection.execute(
                "SELECT thread_id FROM local_thread_catalog ORDER BY thread_id"
            ).fetchall()
            revision = connection.execute(
                "SELECT catalog_revision FROM local_thread_catalog_metadata WHERE id = 1"
            ).fetchone()[0]
        self.assertEqual(remaining, [("thread-keep",)])
        self.assertEqual(revision, 11)

        with closing(sqlite3.connect(backup)) as connection:
            restored_rows = connection.execute(
                "SELECT thread_id FROM local_thread_catalog ORDER BY thread_id"
            ).fetchall()
        self.assertEqual(
            restored_rows,
            [("thread-alpha",), ("thread-beta",), ("thread-keep",)],
        )

    def test_title_mismatch_aborts_entire_batch_without_backup(self) -> None:
        targets = self._targets()
        targets[1]["expected_title"] = "Wrong title"
        self._write_manifest(targets)
        result = self._run(
            "delete-batch",
            "--db",
            str(self.database),
            "--manifest",
            str(self.manifest),
            "--backup-dir",
            str(self.backups),
            "--confirm",
            "DELETE_CONFIRMED_GHOST_BATCH",
        )
        self.assertEqual(result.returncode, 1)
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM local_thread_catalog"
            ).fetchone()[0]
        self.assertEqual(count, 3)
        self.assertFalse(self.backups.exists())

    def test_other_table_reference_aborts_entire_batch(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE related (thread_id TEXT)")
            connection.execute("INSERT INTO related VALUES ('thread-beta')")
            connection.commit()
        self._write_manifest(self._targets())
        result = self._run(
            "delete-batch",
            "--db",
            str(self.database),
            "--manifest",
            str(self.manifest),
            "--backup-dir",
            str(self.backups),
            "--confirm",
            "DELETE_CONFIRMED_GHOST_BATCH",
        )
        self.assertEqual(result.returncode, 1)
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM local_thread_catalog"
            ).fetchone()[0]
        self.assertEqual(count, 3)

    def test_duplicate_thread_ids_are_rejected(self) -> None:
        targets = self._targets()
        targets.append(dict(targets[0]))
        self._write_manifest(targets)
        result = self._run(
            "delete-batch",
            "--db",
            str(self.database),
            "--manifest",
            str(self.manifest),
            "--backup-dir",
            str(self.backups),
            "--confirm",
            "DELETE_CONFIRMED_GHOST_BATCH",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate thread_id", result.stderr)

    def test_missing_query_columns_fail_before_backup(self) -> None:
        for column in ("source_created_at", "source_updated_at", "source_recency_at"):
            with self.subTest(column=column):
                with closing(sqlite3.connect(":memory:")) as connection:
                    connection.execute(
                        "CREATE TABLE local_thread_catalog (" + ", ".join(
                            f'{name} TEXT' + (" PRIMARY KEY" if name == "thread_id" else "")
                            for name in sorted(cleanup.REQUIRED_COLUMNS - {column})
                        ) + ")"
                    )
                    with self.assertRaisesRegex(cleanup.CleanupError, column):
                        cleanup.validate_schema(connection)
        self.assertFalse(self.backups.exists())

    def test_additive_schema_is_supported_without_metadata(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("ALTER TABLE local_thread_catalog ADD COLUMN future_field TEXT")
            connection.execute("DROP TABLE local_thread_catalog_metadata")
            connection.commit()
        result = cleanup.delete_targets(
            database=self.database, targets=self._targets(), backup_dir=self.backups, batch=True
        )
        self.assertEqual(result["deleted"], 2)

    def test_incompatible_metadata_and_triggers_fail_before_backup(self) -> None:
        for sql in (
            "ALTER TABLE local_thread_catalog_metadata RENAME COLUMN catalog_revision TO changed",
            "UPDATE local_thread_catalog_metadata SET catalog_revision = 'invalid'",
            "DELETE FROM local_thread_catalog_metadata",
            "CREATE TRIGGER changed AFTER DELETE ON local_thread_catalog BEGIN SELECT 1; END",
        ):
            with self.subTest(sql=sql):
                with closing(sqlite3.connect(self.database)) as connection:
                    connection.execute("BEGIN")
                    connection.execute(sql)
                    with self.assertRaises(cleanup.CleanupError):
                        cleanup.validate_schema(connection)
                    connection.rollback()
        self.assertFalse(self.backups.exists())

    def test_catalog_requires_single_thread_id_primary_key(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute(
                "CREATE TABLE local_thread_catalog (" + ", ".join(
                    f'{name} TEXT' for name in sorted(cleanup.REQUIRED_COLUMNS)
                ) + ")"
            )
            with self.assertRaisesRegex(cleanup.CleanupError, "primary key"):
                cleanup.validate_schema(connection)

    def test_changed_identifier_type_is_rejected(self) -> None:
        for identifier_type in ("INTEGER", "INTTEXT"):
            with self.subTest(identifier_type=identifier_type):
                with closing(sqlite3.connect(":memory:")) as connection:
                    connection.execute(
                        "CREATE TABLE local_thread_catalog (" + ", ".join(
                            f'{name} ' + (f"{identifier_type} PRIMARY KEY" if name == "thread_id" else "TEXT")
                            for name in sorted(cleanup.REQUIRED_COLUMNS)
                        ) + ")"
                    )
                    with self.assertRaisesRegex(cleanup.CleanupError, "column type"):
                        cleanup.validate_schema(connection)

    def test_schema_is_revalidated_under_write_lock(self) -> None:
        real_validate = cleanup.validate_schema
        transaction_states = []

        def validate(connection):
            transaction_states.append(connection.in_transaction)
            real_validate(connection)

        with patch.object(cleanup, "validate_schema", side_effect=validate):
            cleanup.delete_targets(
                database=self.database, targets=self._targets(), backup_dir=self.backups, batch=True
            )
        self.assertEqual(transaction_states, [False, True])

    def _fail_quick_check(self, on_call: int):
        real_check = cleanup.quick_check
        calls = 0

        def check(connection):
            nonlocal calls
            calls += 1
            if calls == on_call:
                raise cleanup.CleanupError("injected integrity failure")
            return real_check(connection)

        return patch.object(cleanup, "quick_check", side_effect=check)

    def test_precommit_failure_rolls_back_and_preserves_backup(self) -> None:
        with self._fail_quick_check(4):
            with self.assertRaisesRegex(cleanup.CleanupError, "injected"):
                cleanup.delete_targets(
                    database=self.database, targets=self._targets(), backup_dir=self.backups, batch=True
                )
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM local_thread_catalog").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT catalog_revision FROM local_thread_catalog_metadata").fetchone()[0], 10)
        self.assertEqual(len(list(self.backups.glob("*.sqlite"))), 1)

    def test_postcommit_failure_has_distinct_exit_and_preserves_receipt(self) -> None:
        def handler(_):
            cleanup.delete_targets(
                database=self.database, targets=self._targets(), backup_dir=self.backups, batch=True
            )

        stderr = io.StringIO()
        with patch.object(sys, "argv", [str(SCRIPT), "inspect"]), \
                patch.object(cleanup, "inspect_database", side_effect=handler), \
                self._fail_quick_check(5), redirect_stderr(stderr):
            self.assertEqual(cleanup.main(), 2)
        result = json.loads(stderr.getvalue())
        self.assertEqual(result["transaction_status"], "committed")
        self.assertEqual(result["postcheck"], "failed")
        self.assertFalse(result["retry_safe"])
        self.assertEqual(result["deleted"], 2)
        self.assertTrue(Path(result["backup"]).is_file())
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM local_thread_catalog").fetchone()[0], 1)

    def test_missing_confirmation_cannot_delete_or_create_backup(self) -> None:
        result = self._run("delete", "--db", str(self.database), "--thread-id", "thread-alpha",
                           "--expected-title", "Alpha ghost", "--backup-dir", str(self.backups),
                           "--confirm", "wrong")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.backups.exists())


if __name__ == "__main__":
    unittest.main()

