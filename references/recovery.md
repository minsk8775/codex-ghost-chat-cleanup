# Backup Location and Recovery

Read this reference when the user asks where a cleanup backup was stored, wants to recover deleted catalog entries, or reports that the wrong confirmed batch was removed.

## What the Backup Contains

`delete-batch` creates one complete SQLite snapshot before its transaction starts. The filename is:

```text
codex-dev-pre-ghost-cleanup-batch-YYYYMMDD-HHMMSS-microseconds.sqlite
```

The file is written to the absolute `--backup-dir` supplied to the command. The skill should normally use the current writable workspace's `outputs` directory and must report the exact returned `backup` path after deletion. Do not guess the location later.

The snapshot contains the entire local Codex database as it existed immediately before that batch, not only the deleted rows. Restoring it also reverts other local database changes made after the snapshot.

## Before Restoring

1. Choose the backup path reported by the deletion command. Do not substitute an older similarly named file.
2. Run read-only validation against the backup:

   `scripts/catalog_cleanup.py inspect --db <absolute-backup-path>`

3. Confirm that the result reports `"integrity": "ok"` and contains the expected `title (ID)` entries.
4. Fully exit Codex. Check Task Manager and wait until no Codex process remains. Do not restore the live database while Codex is running.
5. Resolve the live database path, normally `%USERPROFILE%\.codex\sqlite\codex-dev.db`, and verify that it is the live file rather than another backup.

## Restore on Windows

Run these steps from PowerShell only after Codex is fully closed. Replace the example backup path with the exact path reported during deletion.

```powershell
$backupPath = "C:\absolute\path\to\codex-dev-pre-ghost-cleanup-batch-....sqlite"
$liveDb = Join-Path $env:USERPROFILE ".codex\sqlite\codex-dev.db"
$safetyCopy = "$liveDb.pre-restore-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"

if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
    throw "Backup not found: $backupPath"
}
if (-not (Test-Path -LiteralPath $liveDb -PathType Leaf)) {
    throw "Live database not found: $liveDb"
}

Copy-Item -LiteralPath $liveDb -Destination $safetyCopy
Copy-Item -LiteralPath $backupPath -Destination $liveDb -Force
```

Keep the `*.pre-restore-*` safety copy until Codex starts normally and the restored task list has been checked. Then restart Codex and verify the expected `title (ID)` entries.

## Stop Conditions

- Do not restore without a verified absolute backup path.
- Do not overwrite the live database while Codex is running.
- Do not delete the pre-restore safety copy during the recovery session.
- Stop if either database fails `PRAGMA quick_check`, the schema is unsupported, the expected entries are absent from the backup, or the live path is ambiguous.
- Recovery replaces the complete local database state. It is not a row-level undo and does not restore server-side conversations.

## A Committed Deletion with a Failed Post-check

Exit code `2` reports `transaction_status: committed`, `postcheck: failed`, `retry_safe: false`, the deleted count, and the exact recovery-backup path. The transaction has already committed; rollback is no longer possible. Preserve this receipt and the backup. Do not replay the deletion command. Inspect only the originally confirmed IDs to determine the current catalog state before considering recovery.

## Old Installation Backups

`install.ps1 -Replace` preserves the previous skill directory as `codex-ghost-chat-cleanup.backup-<timestamp>`. Neither installation nor cleanup deletes these directories or any SQLite recovery backup automatically.

After verifying the replacement installation, a user may explicitly select one exact old installation-backup path for removal. First resolve its absolute path and verify that it is a sibling of the installed skill, has the exact timestamped installation-backup name, contains the expected `SKILL.md`, `agents/openai.yaml`, `scripts/catalog_cleanup.py`, and `references/recovery.md`, and contains no database, recovery snapshot, symlink, or additional user file. A name alone does not prove ownership. If provenance or contents are uncertain, keep it. Do not apply wildcard, age-based, recursive parent-folder, or bulk deletion. User-created backups, recovery snapshots, and pre-restore safety copies remain preserved until the user separately chooses their exact paths.

