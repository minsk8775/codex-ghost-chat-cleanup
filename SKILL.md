---
name: codex-ghost-chat-cleanup
description: Detect and safely remove stale Codex or ChatGPT task-catalog entries that remain as unopenable ghost chats. Use when the user asks to find, check, clean up, remove, or delete a 유령 채팅, ghost chat, stale chat, orphaned task, or an item that appears in Codex but cannot be opened. Do not use for deleting normal accessible conversations.
---

# Codex Ghost Chat Cleanup

Identify an orphaned local catalog entry and remove only that entry after creating a fresh recovery backup.

## Authorization

- Read-only diagnosis is allowed when the user asks to check or identify ghost chats.
- Mutate the live database only when the current user message explicitly asks to delete, remove, clean up, or 정리 the ghost entry. A request such as `유령 채팅 창 삭제 스킬 써줘` contains deletion intent.
- Skill invocation alone does not authorize deleting normal accessible chats or multiple ambiguous candidates.

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
6. If multiple candidates remain, show their titles and ask the user to choose. Do not batch-delete them.

## Delete a Confirmed Ghost

1. Create or select an `outputs` directory in the current writable workspace for the recovery backup.
2. Run the deterministic deletion script with the exact ID and title:

   `scripts/catalog_cleanup.py delete --db <absolute-live-db> --thread-id <id> --expected-title <title> --backup-dir <absolute-output-dir> --confirm DELETE_ONE_CONFIRMED_GHOST`

3. Request the required filesystem or command approval immediately before the live database write when the environment requires it.
4. Allow the script to finish its own backup, transaction, catalog-revision update, and integrity check. Do not replace this with ad hoc SQL.
5. Re-run `inspect` for the target ID and confirm that the row count is zero. Recheck the task list or direct lookup to ensure synchronization did not recreate it.
6. Report the deleted title and ID, before/after catalog totals, integrity result, and recovery-backup path. Suggest restarting Codex only when the sidebar still shows cached state.

## Stop Conditions

- Do not delete the database file itself.
- Do not overwrite the live database with an older backup.
- Do not remove an entry that is readable, active, archived, referenced by another local table, or not an exact title/ID match.
- If the schema check, one-row invariant, backup, transaction, or integrity check fails, stop and report the error. Preserve any created backup.
- This cleanup removes a stale local catalog row; it is not a substitute for supported deletion of a real server-side conversation.
