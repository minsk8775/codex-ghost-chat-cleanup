# Codex Ghost Chat Cleanup

A safety-focused Codex skill for identifying and removing one confirmed stale local task-catalog entry that still appears in the sidebar but can no longer be opened.

> **Unofficial community project.** This repository is not affiliated with or endorsed by OpenAI. It works with a local Codex database schema that may change between Codex versions.

## What it does

- Inspects the local task catalog without modifying it.
- Requires a task to be absent from current tasks, archived tasks, and direct lookup before treating it as a confirmed ghost.
- Deletes only one exact thread ID and title match.
- Creates a fresh SQLite recovery backup before any deletion.
- Uses a transaction, updates the catalog revision when supported, and runs an integrity check.
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

Deletion remains gated by the authorization rules in `SKILL.md`: the current user message must explicitly request removal, and the candidate must be confirmed and unambiguous.

## Releases

Pushing a tag whose name starts with `v` packages the runtime files and publishes a GitHub Release automatically. For example:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Development checks

The validation workflow checks required files, rejects database and secret-file patterns, verifies the Python command interface, and exercises release packaging on every push and pull request.

## License

MIT. See `LICENSE`.

---

## 한국어 요약

열리지 않지만 Codex 목록에 남아 있는 로컬 유령 채팅 항목을 확인하고, 확정된 항목 하나만 백업 후 정리하는 비공식 커뮤니티 스킬입니다. 저장소에는 실제 채팅, 데이터베이스, 백업, 인증 정보 또는 사용자별 절대 경로가 포함되어 있지 않습니다. 설치·업데이트 후에는 Codex를 다시 시작하세요.
