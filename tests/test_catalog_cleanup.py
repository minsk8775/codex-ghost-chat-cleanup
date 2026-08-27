from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "catalog_cleanup.py"


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


if __name__ == "__main__":
    unittest.main()
