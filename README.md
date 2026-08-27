# Codex Ghost Chat Cleanup

A safety-focused Codex skill for identifying stale local task-catalog entries, presenting them as `title (ID)`, and atomically deleting the user-confirmed batch.

> **Unofficial community project.** This repository is not affiliated with or endorsed by OpenAI. It works with a local Codex database schema that may change between Codex versions.

## What it does

- Inspects the local task catalog without modifying it.
- Requires a task to be absent from current tasks, archived tasks, and direct lookup before treating it as a confirmed ghost.
- Presents every confirmed candidate as `title (thread_id)` and requires a follow-up confirmation of all or selected numbered items.
- Creates one full SQLite recovery backup before changing the confirmed batch.
- Deletes the entire confirmed set in one transaction, updates the catalog revision when supported, and runs an integrity check.
- Stops on schema mismatch, ambiguity, references from other tables, or failed validation.

It does **not** delete normal accessible conversations or replace supported server-side conversation deletion.

## Privacy

The repository contains only skill instructions, UI metadata, and a deterministic cleanup script. It contains no chat contents, Codex databases, database backups, credentials, tokens, or user-specific absolute paths. The included `.gitignore` blocks common database, backup, log, and secret-file patterns from accidental commits.

## Install

### Clone directly into the Codex skills directory

Windows PowerShell:

```powershell
git clone https://github.com/minsk8775/codex-ghost-chat-cleanup.git "$env:USERPROFILE\.codex\skills\codex-ghost-chat-cleanup"
```

macOS or Linux:

```bash
git clone https://github.com/minsk8775/codex-ghost-chat-cleanup.git ~/.codex/skills/codex-ghost-chat-cleanup
```

Restart Codex after installation.

### Install from a downloaded copy or Release ZIP on Windows

Extract the download, open PowerShell in the extracted folder, and run:

```powershell
.\install.ps1
```

If the skill is already installed, `-Replace` moves the old installation to a timestamped backup directory before copying the new version:

```powershell
.\install.ps1 -Replace
```

## Update

For a direct Git clone installation:

```powershell
git -C "$env:USERPROFILE\.codex\skills\codex-ghost-chat-cleanup" pull --ff-only
```

Restart Codex after updating. Release ZIP installations can be updated by downloading the latest release and running `install.ps1 -Replace`.

## Use

Read-only diagnosis:

```text
$codex-ghost-chat-cleanup inspect my Codex task list for a ghost chat without deleting anything.
```

The skill first diagnoses candidates and displays a numbered review list such as:

```text
1. Project cleanup (01abc...)
2. [제목 없음] (01def...)
```

The user must then confirm `전체 삭제` or select exact numbered items in a follow-up message. Only that frozen selection is written to the batch manifest and deleted. If any target fails validation, the entire batch is aborted without partial deletion.

## Backup and recovery

Every successful batch deletion first creates one complete SQLite snapshot named like:

```text
codex-dev-pre-ghost-cleanup-batch-YYYYMMDD-HHMMSS-microseconds.sqlite
```

The backup is stored in the writable `outputs` directory selected for that run, and the skill reports its absolute path. It contains the catalog state from immediately before the batch deletion.

To restore, fully exit Codex, preserve a separate copy of the current live database, validate the selected backup, and copy the backup over `%USERPROFILE%\.codex\sqlite\codex-dev.db`. Detailed safeguards and PowerShell steps are in [`references/recovery.md`](references/recovery.md). Never restore while Codex is running.

## Releases

Pushing a tag whose name starts with `v` packages the runtime files and publishes a GitHub Release automatically. For example:

```bash
git tag v1.1.0
git push origin v1.1.0
```

## Development checks

The validation workflow checks required files, rejects database and secret-file patterns, runs atomic batch-deletion tests against temporary SQLite fixtures, verifies the command interface, and exercises release packaging on every push and pull request.

## License

MIT. See `LICENSE`.

---

## 한국어 요약

열리지 않지만 Codex 목록에 남아 있는 로컬 유령 채팅 후보를 `제목 (ID)` 형식으로 보여주고, 사용자가 확인한 항목들을 한 번의 백업과 트랜잭션으로 일괄 정리하는 비공식 커뮤니티 스킬입니다. 실제 채팅, 데이터베이스, 백업, 인증 정보 또는 사용자별 절대 경로는 저장소에 포함되지 않습니다. 백업 위치와 복구 절차는 `references/recovery.md`에 설명되어 있습니다.
