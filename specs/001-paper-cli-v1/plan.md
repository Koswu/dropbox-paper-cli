# Implementation Plan: Dropbox Paper CLI v1.0

**Branch**: `001-paper-cli-v1` | **Date**: 2025-07-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-paper-cli-v1/spec.md`

## Summary

Build a Python CLI tool (`paper`) that wraps all Dropbox Paper SDK operations as grouped subcommands (`auth`, `files`, `cache`, `sharing`) with local metadata caching and keyword search. Uses Typer for the CLI framework, OAuth2 PKCE for authentication with filesystem token storage, SQLite with FTS5 for sub-second local search, and the official Dropbox Python SDK for all API interactions. Every command supports `--json` for machine-parseable output and `--verbose` for diagnostics, with auto-retry on transient failures.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: Typer (CLI framework), dropbox (official Dropbox Python SDK)
**Storage**: SQLite (built-in `sqlite3` module) for local metadata cache; JSON files for token storage
**Testing**: pytest (TDD mandated by constitution); `typer.testing.CliRunner` for CLI tests; `unittest.mock` for Dropbox SDK mocking
**Target Platform**: Linux and macOS (primary); Windows best-effort
**Project Type**: CLI tool
**Performance Goals**: Local keyword search <1s for 10,000 items (SC-004); incremental sync <30s for <100 changes (SC-005); full sync <5min for 10,000 items (SC-010)
**Constraints**: Single-user CLI; all SDK commands require network; only local cache search works offline
**Scale/Scope**: Single-user tool; up to 10,000 cached metadata items; ~15 CLI commands across 4 command groups

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Evidence |
|---|-----------|--------|----------|
| I | CLI-First | ✅ PASS | All features exposed as Typer commands; stdout for data, stderr for errors; `--json` flag on every command; meaningful exit codes (0–6) |
| II | SDK Wrapper + Extensions | ✅ PASS | SDK wrapper layer in `services/dropbox_service.py`; extension feature (local cache) in separate `services/cache_service.py` and `db/` module; no reverse dependency |
| III | Local Metadata Cache | ✅ PASS | SQLite with FTS5 for name search; metadata only (no content); idempotent sync with cursor; incremental updates |
| IV | Agent-Friendly | ✅ PASS | `--json` on every command with stable keys; JSON errors include `error` + `code`; no interactive prompts in normal operation; descriptive `--help` text |
| V | Auth Flexibility | ✅ PASS | PKCE (primary) and Authorization Code flows; token persisted in `~/.dropbox-paper-cli/tokens.json` with `0600` permissions; auto-refresh; modular auth service |
| VI | Test-First (NON-NEGOTIABLE) | ✅ PASS | pytest mandated; TDD Red-Green-Refactor cycle; tests/ mirrors src/ structure; Dropbox SDK mocked for unit tests |
| VII | Simplicity | ✅ PASS | No features beyond spec; standard library `sqlite3` (no ORM); simple retry decorator (no tenacity); single-file token storage (no keyring in v1); FTS content search out of scope |

**Gate Result**: ✅ ALL PRINCIPLES SATISFIED — proceed to implementation.

## Project Structure

### Documentation (this feature)

```text
specs/001-paper-cli-v1/
├── plan.md              # This file
├── research.md          # Phase 0 output — technology research and decisions
├── data-model.md        # Phase 1 output — entity definitions and SQLite schema
├── quickstart.md        # Phase 1 output — setup and usage guide
├── contracts/
│   └── cli-contract.md  # Phase 1 output — CLI interface contract
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/dropbox_paper_cli/
├── __init__.py              # Package version
├── __main__.py              # Entry point: python -m dropbox_paper_cli
├── app.py                   # Main Typer app assembly, global options callback
├── cli/                     # Command group modules (thin: parse args → call service → format output)
│   ├── __init__.py
│   ├── auth.py              # paper auth login/logout/status
│   ├── files.py             # paper files list/metadata/read/move/copy/delete/create-folder/link
│   ├── cache.py             # paper cache sync/search
│   └── sharing.py           # paper sharing info
├── services/                # Business logic (orchestrates SDK calls and local operations)
│   ├── __init__.py
│   ├── auth_service.py      # OAuth2 PKCE + Authorization Code flows, token CRUD
│   ├── dropbox_service.py   # SDK wrapper: file ops, Paper export, sharing links
│   ├── cache_service.py     # Sync orchestration, search delegation
│   └── sharing_service.py   # Shared folder info retrieval
├── models/                  # Data classes (pure data, no side effects)
│   ├── __init__.py
│   ├── auth.py              # AuthToken dataclass
│   ├── items.py             # DropboxItem, PaperDocument dataclasses
│   ├── sharing.py           # SharingInfo, MemberInfo dataclasses
│   └── cache.py             # CachedMetadata, SyncState, SyncResult dataclasses
├── lib/                     # Shared utilities (stateless, reusable)
│   ├── __init__.py
│   ├── output.py            # OutputFormatter: JSON/human-readable, success/error
│   ├── errors.py            # AppError hierarchy, exit code enum, error codes
│   ├── retry.py             # @with_retry decorator: exponential backoff, verbose logging
│   ├── url_parser.py        # resolve_target(): URL → ID extraction, input normalization
│   └── config.py            # Paths (~/.dropbox-paper-cli/), app key, defaults
└── db/                      # Database layer (SQLite only, no ORM)
    ├── __init__.py
    ├── connection.py         # CacheDatabase: open/close, WAL mode, corruption recovery
    └── schema.py             # Schema DDL, FTS5 setup, migrations

tests/
├── conftest.py              # Shared fixtures: mock Dropbox client, CLI runner, temp cache DB
├── unit/
│   ├── cli/
│   │   ├── test_auth.py
│   │   ├── test_files.py
│   │   ├── test_cache.py
│   │   └── test_sharing.py
│   ├── services/
│   │   ├── test_auth_service.py
│   │   ├── test_dropbox_service.py
│   │   ├── test_cache_service.py
│   │   └── test_sharing_service.py
│   ├── models/
│   │   ├── test_items.py
│   │   └── test_auth.py
│   ├── lib/
│   │   ├── test_output.py
│   │   ├── test_errors.py
│   │   ├── test_retry.py
│   │   ├── test_url_parser.py
│   │   └── test_config.py
│   └── db/
│       ├── test_connection.py
│       └── test_schema.py
└── integration/             # Live API tests (opt-in, requires real Dropbox credentials)
    └── test_smoke.py

pyproject.toml               # Project metadata, dependencies, tool config (ruff, pytest)
```

**Structure Decision**: Single-project layout with `src/` layout (`src/dropbox_paper_cli/`) for proper package isolation. The `src/` layout prevents accidental imports of the package during testing and is the recommended Python packaging structure. Command modules in `cli/` are thin wrappers that delegate to `services/` for business logic and `lib/output.py` for formatting — this keeps CLI concerns (arg parsing, output formatting) separate from business logic (SDK calls, caching).

### Module Dependency Graph

```
cli/ ──→ services/ ──→ models/
  │          │             │
  │          ├──→ lib/     │
  │          │     ↑       │
  │          └──→ db/      │
  │                        │
  └──→ lib/output.py       │
  └──→ lib/errors.py  ←───┘
```

**Key constraints** (per Principle II):
- `cli/` depends on `services/` and `lib/` — never on `db/` directly
- `services/dropbox_service.py` (SDK wrapper) does NOT depend on `services/cache_service.py` (extension)
- `services/cache_service.py` MAY depend on `services/dropbox_service.py` (for sync)
- `db/` depends only on `models/` and `lib/`
- `models/` depends on nothing (pure data)
- `lib/` depends on nothing (stateless utilities)

## Complexity Tracking

> No violations detected. All design decisions align with constitution principles.
