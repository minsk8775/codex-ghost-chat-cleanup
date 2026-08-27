---
name: codex-ghost-chat-cleanup
description: Detect stale Codex or ChatGPT task-catalog entries that remain as unopenable ghost chats, present confirmed candidates as title (ID), and batch-delete only the set the user confirms after creating a recovery backup. Use when the user asks to find, check, clean up, remove, or delete a 유령 채팅, ghost chat, stale chat, orphaned task, or an item that appears in Codex but cannot be opened. Do not use for deleting normal accessible conversations.
---

# Codex Ghost Chat Cleanup

Compare the complete available task sources, present confirmed ghost candidates for review, and remove the user-confirmed set atomically after creating a fresh recovery backup.

## Authorization

- Read-only diagnosis is allowed when the user asks to check, identify, delete, or clean up ghost chats.
- A cleanup request authorizes diagnosis and presentation of candidates, but not the final database mutation. Delete only after the user reviews the displayed batch and confirms the exact items in a follow-up message.
- The follow-up may confirm all displayed candidates or select specific numbered items. Do not infer confirmation from the initial request, silence, or skill invocation alone.
- Never delete normal accessible chats, ambiguous candidates, or any item outside the confirmed displayed batch.

## Diagnose

1. List up to 50 current tasks and all pages of archived tasks using the Codex task tools. Stop before deletion if any source or host needed for comparison is unavailable.
2. Locate the live database rather than assuming an old backup is live. Prefer `%USERPROFILE%\.codex\sqlite\codex-dev.db` only after resolving and verifying its absolute path and schema.
3. Run `scripts/catalog_cleanup.py inspect --db <absolute-live-db>` with the bundled workspace Python runtime.
4. Treat an entry as a confirmed ghost only when all are true:
   - It exists in `local_thread_catalog`.
   - It is absent from the current task list and every archived-task page.
   - Direct task lookup by its ID finds no readable task.
   - Its title or ID matches the item the user wants removed, or it is the only unambiguous candidate.
5. If the current-task result reaches its 50-item limit, do not classify older unlisted catalog rows as ghosts from absence alone. Require an exact user-supplied title or ID plus failed direct lookup.
6. Directly look up every candidate by its thread ID. Exclude any readable, active, archived, ambiguous, or otherwise unconfirmed entry.

## Present and Confirm the Batch

1. Show every confirmed candidate as a numbered list using exactly this user-facing format:

   `<title> (<thread_id>)`

   Use `[제목 없음] (<thread_id>)` when the stored title is empty. Never show an ID by itself or make it the primary label.
2. Ask the user to confirm `전체 삭제` or specify the numbered items to delete. Stop and wait for that follow-up confirmation even when only one candidate exists.
3. Freeze the confirmed selection. Create a JSON manifest in the writable `work` directory containing only those targets, with each exact `thread_id`, `expected_title`, and `expected_source_kind`.
4. Do not add newly discovered candidates to the manifest without showing them and receiving another confirmation.

## Batch Delete the Confirmed Set

1. Create or select an `outputs` directory in the current writable workspace. The script writes one full SQLite recovery backup there before changing the live database.
2. Run the deterministic batch deletion command with the confirmed manifest:

   `scripts/catalog_cleanup.py delete-batch --db <absolute-live-db> --manifest <absolute-confirmed-manifest> --backup-dir <absolute-output-dir> --confirm DELETE_CONFIRMED_GHOST_BATCH`

3. Request the required filesystem or command approval immediately before the live database write when the environment requires it.
4. Allow the script to validate every target before creating the backup, then finish its single transaction, catalog-revision update, and integrity check. Do not replace this with ad hoc SQL or repeated single-row commands.
5. Re-run `inspect` for every confirmed thread ID and confirm that all row counts are zero. Recheck direct task lookup to ensure synchronization did not recreate an item.
6. Report every deleted item as `title (ID)`, the deleted count, before/after catalog totals, integrity result, and the absolute recovery-backup path.
7. Explain that the backup is a complete pre-deletion database snapshot. When the user asks where backups are stored, how to restore one, or reports a mistaken deletion, read [references/recovery.md](references/recovery.md) and follow it.

## Stop Conditions

- Do not delete the database file itself.
- Do not overwrite the live database with an older backup.
- Do not remove an entry that is readable, active, archived, referenced by another local table, outside the confirmed manifest, or not an exact title/ID/source-kind match.
- If any one target fails validation or changes before deletion, abort the entire batch. Do not partially delete the remaining targets.
- If the schema check, unique-ID invariant, backup, transaction, target-count check, or integrity check fails, stop and report the error. Preserve any created backup.
- This cleanup removes a stale local catalog row; it is not a substitute for supported deletion of a real server-side conversation.
