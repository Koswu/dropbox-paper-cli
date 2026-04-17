# Tasks: Dropbox Paper CLI v1.0

**Input**: Design documents from `/specs/001-paper-cli-v1/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/cli-contract.md ✅, quickstart.md ✅

**Tests**: TDD is **mandatory** per constitution Principle VI. Every implementation task has a preceding test task. Tests MUST be written FIRST and verified to FAIL before implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Exact file paths included in all descriptions

## Path Conventions

- Source: `src/dropbox_paper_cli/`
- Tests: `tests/` (mirrors `src/` structure)
- Config: `pyproject.toml` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Initialize the Python project, install dependencies, configure tooling, and create the full package skeleton.

- [X] T001 Initialize Python project with uv, create src/dropbox_paper_cli/ package layout with all __init__.py files per plan.md project structure
- [X] T002 Configure pyproject.toml with project metadata, entry point `paper`, dependencies (typer, dropbox), and dev dependencies (pytest, ruff)
- [X] T003 [P] Configure ruff (select rules, format), pytest (testpaths, src layout), and ty (type checking) in pyproject.toml
- [X] T004 [P] Create shared test fixtures (mock Dropbox client factory, typer.testing.CliRunner, tmp_path helpers) in tests/conftest.py

**Checkpoint**: `uv sync` succeeds, `uv run pytest --collect-only` finds conftest.py, `uv run ruff check src/` runs clean on empty package.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented. These are cross-cutting utilities, base models, the app shell, and the entry point.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests for Foundational Phase

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T005 [P] Write tests for AppError hierarchy, ExitCode enum (0–6), and error code constants in tests/unit/lib/test_errors.py
- [X] T006 [P] Write tests for config paths (~/.dropbox-paper-cli/), app key, and default values in tests/unit/lib/test_config.py
- [X] T007 [P] Write tests for OutputFormatter JSON/human-readable formatting and error output to stderr in tests/unit/lib/test_output.py
- [X] T008 [P] Write tests for resolve_target() URL-to-ID regex extraction, raw ID passthrough, and path normalization in tests/unit/lib/test_url_parser.py
- [X] T009 [P] Write tests for @with_retry decorator: exponential backoff timing, retryable error detection, max retries, verbose logging in tests/unit/lib/test_retry.py
- [X] T010 [P] Write tests for DropboxItem and PaperDocument dataclasses including SDK metadata mapping (FileMetadata→file, FolderMetadata→folder) in tests/unit/models/test_items.py

### Implementation for Foundational Phase

- [X] T011 [P] Implement AppError hierarchy, ExitCode enum (0=success through 6=permission), and machine-readable error code constants in src/dropbox_paper_cli/lib/errors.py
- [X] T012 [P] Implement config paths (CONFIG_DIR, TOKEN_PATH, CACHE_DB_PATH), APP_KEY, and defaults in src/dropbox_paper_cli/lib/config.py
- [X] T013 [P] Implement resolve_target() with regex pattern r'https?://(?:www\.)?dropbox\.com/scl/fi/([^/]+)/.*' and input normalization in src/dropbox_paper_cli/lib/url_parser.py
- [X] T014 [P] Implement @with_retry decorator with base_delay=1s, max_retries=3, exponential backoff, Retry-After header support, and verbose stderr logging in src/dropbox_paper_cli/lib/retry.py
- [X] T015 [P] Implement DropboxItem and PaperDocument dataclasses with from_sdk() class methods for SDK metadata mapping in src/dropbox_paper_cli/models/items.py
- [X] T016 Implement OutputFormatter with success/error methods, JSON (--json) and human-readable output, stderr error formatting with error+code keys in src/dropbox_paper_cli/lib/output.py
- [X] T017 Implement main Typer app assembly with @app.callback() for global --json, --verbose, --version options in src/dropbox_paper_cli/app.py
- [X] T018 Implement entry point (python -m dropbox_paper_cli → app) in src/dropbox_paper_cli/__main__.py

**Checkpoint**: Foundation ready — `uv run paper --help` shows app with global options, `uv run paper --version` prints version, `uv run pytest tests/unit/lib/ tests/unit/models/test_items.py` all green.

---

## Phase 3: User Story 1 — Authenticate and Connect (Priority: P1) 🎯 MVP

**Goal**: User installs the CLI, runs `paper auth login`, completes OAuth2 PKCE flow in browser, and the CLI securely stores the token. Subsequent commands auto-use and auto-refresh the stored token. `paper auth logout` clears credentials. `paper auth status` shows current auth state.

**Independent Test**: Run `paper auth login`, complete OAuth2 flow, verify token stored at `~/.dropbox-paper-cli/tokens.json` with 0600 permissions. Run `paper auth status` to confirm. Run `paper auth logout` to clear.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T019 [P] [US1] Write tests for AuthToken dataclass (validation rules, expiry check, serialization to/from JSON) in tests/unit/models/test_auth.py
- [X] T020 [P] [US1] Write tests for auth_service: PKCE flow initiation, AuthCode flow initiation, token persistence (atomic write, 0600 perms), token loading, auto-refresh, token revocation/deletion in tests/unit/services/test_auth_service.py
- [X] T021 [P] [US1] Write tests for auth CLI commands: login (both --flow pkce and --flow code), logout, status (authenticated/unauthenticated/expired) with human-readable and --json output in tests/unit/cli/test_auth.py

### Implementation for User Story 1

- [X] T022 [US1] Implement AuthToken dataclass with validation (non-empty tokens, positive expires_at), is_expired property, and JSON serialization in src/dropbox_paper_cli/models/auth.py
- [X] T023 [US1] Implement auth_service: OAuth2 PKCE flow (DropboxOAuth2FlowNoRedirect with use_pkce=True), AuthCode flow, token CRUD (atomic file write with os.rename, 0600 perms), auto-refresh (Dropbox client with oauth2_refresh_token) in src/dropbox_paper_cli/services/auth_service.py
- [X] T024 [US1] Implement auth CLI commands (login with --flow flag, logout, status) with human-readable and JSON output in src/dropbox_paper_cli/cli/auth.py
- [X] T025 [US1] Register auth command group via app.add_typer() in src/dropbox_paper_cli/app.py

**Checkpoint**: User Story 1 fully functional — `uv run paper auth login` guides through OAuth2, `paper auth status` shows account info, `paper auth logout` clears token. `uv run pytest tests/unit/models/test_auth.py tests/unit/services/test_auth_service.py tests/unit/cli/test_auth.py` all green.

---

## Phase 4: User Story 2 — Browse and Inspect Files and Folders (Priority: P1)

**Goal**: Authenticated user runs `paper files list [PATH]` to see directory contents, `paper files metadata <TARGET>` for detailed item info, and `paper files link <TARGET>` to get/create sharing links. Supports Dropbox Paper URLs, file IDs, and paths as input. Both human-readable and JSON output.

**Independent Test**: List root folder, list a subfolder, get metadata for a file (by path, by ID, by URL), get a sharing link. Verify both human-readable and --json output formats.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T026 [P] [US2] Write tests for dropbox_service browse operations: list_folder (flat and --recursive), get_metadata (file and folder), get_or_create_sharing_link, with mock SDK responses in tests/unit/services/test_dropbox_service.py
- [X] T027 [P] [US2] Write tests for files CLI browse commands: list (root, subfolder, --recursive, empty folder), metadata (by path, by ID, by URL), link, with human-readable and --json output, error cases (not found, auth error) in tests/unit/cli/test_files.py

### Implementation for User Story 2

- [X] T028 [US2] Implement dropbox_service with list_folder (files_list_folder + pagination), get_metadata (files_get_metadata), get_or_create_sharing_link (sharing_create_shared_link_with_settings) using @with_retry in src/dropbox_paper_cli/services/dropbox_service.py
- [X] T029 [US2] Implement files CLI browse commands (list with PATH and --recursive, metadata with TARGET, link with TARGET) using resolve_target() for URL/ID/path input in src/dropbox_paper_cli/cli/files.py
- [X] T030 [US2] Register files command group via app.add_typer() in src/dropbox_paper_cli/app.py

**Checkpoint**: User Story 2 fully functional — `paper files list`, `paper files metadata <path>`, `paper files link <path>` all work. `uv run pytest tests/unit/services/test_dropbox_service.py tests/unit/cli/test_files.py` all green.

---

## Phase 5: User Story 3 — Organize Files and Folders (Priority: P1)

**Goal**: Authenticated user can `paper files create-folder <PATH>`, `paper files move <SRC> <DST>`, `paper files copy <SRC> <DST>`, and `paper files delete <TARGET>` to manage their Dropbox Paper directory structure entirely from the terminal.

**Independent Test**: Create a folder, move a file into it, copy a file, delete an item. Verify confirmation output and error handling (conflict, not found, permission denied) in both output modes.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T031 [P] [US3] Write tests for dropbox_service organization operations: move_item (files_move_v2), copy_item (files_copy_v2), delete_item (files_delete_v2), create_folder (files_create_folder_v2), with conflict/not-found/permission error handling in tests/unit/services/test_dropbox_service.py
- [X] T032 [P] [US3] Write tests for files CLI organization commands: create-folder, move (path and URL source), copy, delete, with success confirmations and error output in tests/unit/cli/test_files.py

### Implementation for User Story 3

- [X] T033 [US3] Add move_item, copy_item, delete_item, and create_folder methods with @with_retry to dropbox_service in src/dropbox_paper_cli/services/dropbox_service.py
- [X] T034 [US3] Add create-folder, move, copy, delete CLI commands with resolve_target() support to src/dropbox_paper_cli/cli/files.py

**Checkpoint**: User Story 3 fully functional — all file organization commands work with proper error handling. `uv run pytest tests/unit/services/test_dropbox_service.py tests/unit/cli/test_files.py` all green.

---

## Phase 6: User Story 4 — Read Paper Document Content (Priority: P1)

**Goal**: User or AI agent runs `paper files read <TARGET>` and the CLI outputs the Paper document content as Markdown to stdout. With `--json`, the content is wrapped in a structured JSON object with metadata. This is the core value proposition for AI agent integration.

**Independent Test**: Read a known Paper document by file ID, by path, and by URL. Verify Markdown content on stdout. Verify JSON output wraps content with metadata. Verify error on non-Paper file or folder target.

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T035 [P] [US4] Write tests for dropbox_service Paper content export: export_paper_content (files_export → markdown), error on non-Paper file, error on folder target in tests/unit/services/test_dropbox_service.py
- [X] T036 [P] [US4] Write tests for files CLI read command: raw Markdown output, --json output with content+metadata, URL input, error cases (not found, not a Paper doc) in tests/unit/cli/test_files.py

### Implementation for User Story 4

- [X] T037 [US4] Add export_paper_content method (dbx.files_export → markdown string) with @with_retry to dropbox_service in src/dropbox_paper_cli/services/dropbox_service.py
- [X] T038 [US4] Add read CLI command with TARGET input (resolve_target), raw Markdown stdout and --json metadata wrapper to src/dropbox_paper_cli/cli/files.py

**Checkpoint**: User Story 4 fully functional — `paper files read <id>` outputs Markdown, `paper --json files read <url>` outputs structured JSON. `uv run pytest tests/unit/services/test_dropbox_service.py tests/unit/cli/test_files.py` all green.

---

## Phase 7: User Story 5 — Sync and Search Local Metadata Cache (Priority: P2)

**Goal**: User runs `paper cache sync` to download the full Dropbox directory tree metadata into a local SQLite database with FTS5 indexing. Subsequent syncs are incremental (cursor-based). `paper cache search <QUERY>` performs sub-second local keyword search by file/folder name without any API calls.

**Independent Test**: Run `paper cache sync`, verify local DB is populated with metadata. Run `paper cache search "meeting"`, verify sub-second results. Run sync again, verify incremental (only changes fetched). Search with `--type file`, `--limit 5`, and `--json` flags.

### Tests for User Story 5

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T039 [P] [US5] Write tests for CachedMetadata, SyncState, and SyncResult dataclasses in tests/unit/models/test_cache.py
- [X] T040 [P] [US5] Write tests for CacheDatabase: open/close context manager, WAL mode activation, corruption recovery (delete and recreate) in tests/unit/db/test_connection.py
- [X] T041 [P] [US5] Write tests for schema DDL: metadata table creation, FTS5 virtual table, insert/update/delete triggers, sync_state table, schema_version in tests/unit/db/test_schema.py
- [X] T042 [P] [US5] Write tests for cache_service: full sync (list_folder → insert all), incremental sync (cursor → continue), delete handling, keyword search via FTS5 MATCH, type filter, result limit in tests/unit/services/test_cache_service.py
- [X] T043 [P] [US5] Write tests for cache CLI commands: sync (full and incremental output), sync --full, search (human-readable results, --json, --type file/folder, --limit N, empty results) in tests/unit/cli/test_cache.py

### Implementation for User Story 5

- [X] T044 [P] [US5] Implement CachedMetadata, SyncState, and SyncResult dataclasses in src/dropbox_paper_cli/models/cache.py
- [X] T045 [US5] Implement CacheDatabase context manager with WAL mode, sqlite3.connect, corruption recovery (catch DatabaseError → delete → recreate) in src/dropbox_paper_cli/db/connection.py
- [X] T046 [US5] Implement schema DDL (metadata table, indexes, FTS5 virtual table, FTS sync triggers, sync_state table, schema_version) in src/dropbox_paper_cli/db/schema.py
- [X] T047 [US5] Implement cache_service: full sync (list_folder_recursive → upsert), incremental sync (cursor → list_folder_continue), deleted entry removal, FTS5 keyword search with type filter and limit in src/dropbox_paper_cli/services/cache_service.py
- [X] T048 [US5] Implement cache CLI commands (sync with --full flag, search with QUERY/--type/--limit) with human-readable and JSON output in src/dropbox_paper_cli/cli/cache.py
- [X] T049 [US5] Register cache command group via app.add_typer() and add temp cache DB fixture to tests/conftest.py in src/dropbox_paper_cli/app.py

**Checkpoint**: User Story 5 fully functional — `paper cache sync` populates local SQLite, `paper cache search "keyword"` returns sub-second results. `uv run pytest tests/unit/db/ tests/unit/models/test_cache.py tests/unit/services/test_cache_service.py tests/unit/cli/test_cache.py` all green.

---

## Phase 8: User Story 6 — Get Shared Folder Information (Priority: P3)

**Goal**: User runs `paper sharing info <TARGET>` to see shared folder members, their roles (owner/editor/viewer), and sharing policy. Supports folder path, ID, or URL as input.

**Independent Test**: Query sharing info for a known shared folder. Verify members list with roles. Verify error for non-shared folder. Test both human-readable and --json output.

### Tests for User Story 6

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T050 [P] [US6] Write tests for SharingInfo and MemberInfo dataclasses and SDK response mapping in tests/unit/models/test_sharing.py
- [X] T051 [P] [US6] Write tests for sharing_service: get_folder_metadata, list_folder_members (with pagination via list_folder_members_continue), non-shared folder error in tests/unit/services/test_sharing_service.py
- [X] T052 [P] [US6] Write tests for sharing CLI info command: shared folder output (members, roles), --json output, non-shared folder error, not-found error in tests/unit/cli/test_sharing.py

### Implementation for User Story 6

- [X] T053 [P] [US6] Implement SharingInfo and MemberInfo dataclasses with from_sdk() mapping in src/dropbox_paper_cli/models/sharing.py
- [X] T054 [US6] Implement sharing_service: get_sharing_info (sharing_get_folder_metadata + sharing_list_folder_members with cursor pagination) with @with_retry in src/dropbox_paper_cli/services/sharing_service.py
- [X] T055 [US6] Implement sharing CLI info command with TARGET input (resolve_target), member table formatting, and --json output in src/dropbox_paper_cli/cli/sharing.py
- [X] T056 [US6] Register sharing command group via app.add_typer() in src/dropbox_paper_cli/app.py

**Checkpoint**: User Story 6 fully functional — `paper sharing info "/Shared Folder"` shows members and roles. `uv run pytest tests/unit/models/test_sharing.py tests/unit/services/test_sharing_service.py tests/unit/cli/test_sharing.py` all green.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end validation, code quality enforcement, and integration testing across all user stories.

- [X] T057 [P] Create integration smoke test scaffold (opt-in, requires real Dropbox credentials) covering auth→list→read→sync→search flow in tests/integration/test_smoke.py
- [X] T058 [P] Run ruff check and ruff format on all src/ and tests/ files, fix any violations
- [X] T059 [P] Run ty type check on all source files in src/dropbox_paper_cli/, fix any type errors
- [X] T060 Run full pytest suite (`uv run pytest`) and verify all 61+ tests pass with zero failures
- [X] T061 Validate quickstart.md workflows: verify all documented commands (`paper auth login`, `paper files list`, `paper cache sync`, etc.) match implemented CLI interface

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup (Phase 1) — **BLOCKS all user stories**
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2)
- **User Story 2 (Phase 4)**: Depends on Foundational (Phase 2) + User Story 1 (auth required for SDK calls)
- **User Story 3 (Phase 5)**: Depends on User Story 2 (extends same dropbox_service.py and cli/files.py)
- **User Story 4 (Phase 6)**: Depends on User Story 2 (extends same dropbox_service.py and cli/files.py)
- **User Story 5 (Phase 7)**: Depends on Foundational (Phase 2) + User Story 2 (needs dropbox_service.list_folder for sync)
- **User Story 6 (Phase 8)**: Depends on Foundational (Phase 2) + User Story 1 (auth required, but separate files from US2–US4)
- **Polish (Phase 9)**: Depends on all user stories being complete

### User Story Dependencies

```
Phase 1 (Setup)
    └──→ Phase 2 (Foundational)
              ├──→ US1 (Auth) ──→ US2 (Browse) ──┬──→ US3 (Organize)
              │                                    ├──→ US4 (Read Content)
              │                                    └──→ US5 (Cache/Search)
              └──→ US6 (Sharing Info) [independent once auth exists]
```

- **US3 and US4**: Both depend on US2 (same files) but are independent of each other — execute sequentially to avoid file conflicts
- **US5**: Depends on US2's dropbox_service.list_folder — but has its own separate files (db/, cache_service, cli/cache.py)
- **US6**: Fully independent — separate models, service, and CLI module

### Within Each User Story (TDD Cycle)

1. **All test tasks [P]** can be written in parallel (different test files)
2. Tests MUST be run and verified to **FAIL** before implementation begins
3. Models before services (services depend on model types)
4. Services before CLI commands (CLI delegates to services)
5. Register command group in app.py last (integration point)

### Parallel Opportunities

**Phase 2 — All test tasks (T005–T010)** can run in parallel:
```
T005 (test_errors)  ║  T006 (test_config)  ║  T007 (test_output)
T008 (test_url)     ║  T009 (test_retry)   ║  T010 (test_items)
```

**Phase 2 — Independent implementations (T011–T015)** can run in parallel:
```
T011 (errors)  ║  T012 (config)  ║  T013 (url_parser)  ║  T014 (retry)  ║  T015 (items)
```

**Each user story — test tasks** can run in parallel:
```
US1: T019 (test_auth_model) ║ T020 (test_auth_service) ║ T021 (test_auth_cli)
US5: T039 (test_cache_model) ║ T040 (test_db_conn) ║ T041 (test_schema) ║ T042 (test_cache_svc) ║ T043 (test_cache_cli)
```

**Independent user stories** (once their deps are met):
```
After US2: US3 ║ US4 ║ US5 (if file conflicts are managed)
After US1: US6 (fully separate files)
```

---

## Parallel Example: User Story 5 (Cache/Search)

```bash
# Launch all test-writing tasks in parallel (5 different test files):
T039: "Write tests for cache models in tests/unit/models/test_cache.py"
T040: "Write tests for CacheDatabase in tests/unit/db/test_connection.py"
T041: "Write tests for schema DDL in tests/unit/db/test_schema.py"
T042: "Write tests for cache_service in tests/unit/services/test_cache_service.py"
T043: "Write tests for cache CLI in tests/unit/cli/test_cache.py"

# Then implement model (independent file):
T044: "Implement cache models in src/dropbox_paper_cli/models/cache.py"

# Then sequential DB → service → CLI chain:
T045: "Implement CacheDatabase in src/dropbox_paper_cli/db/connection.py"
T046: "Implement schema DDL in src/dropbox_paper_cli/db/schema.py"
T047: "Implement cache_service in src/dropbox_paper_cli/services/cache_service.py"
T048: "Implement cache CLI in src/dropbox_paper_cli/cli/cache.py"
T049: "Register cache group in src/dropbox_paper_cli/app.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (**CRITICAL — blocks all stories**)
3. Complete Phase 3: User Story 1 (Auth)
4. Complete Phase 4: User Story 2 (Browse)
5. **STOP and VALIDATE**: `paper auth login` → `paper files list` → `paper files metadata <file>` works end-to-end
6. This is a deployable, useful CLI tool at this point

### Incremental Delivery

1. **Setup + Foundational** → Foundation ready (Phases 1–2)
2. **+ User Story 1** → Auth works (Phase 3) — required gateway
3. **+ User Story 2** → Browse works (Phase 4) — **MVP!** 🎯
4. **+ User Story 3** → Organize works (Phase 5) — core pain point solved
5. **+ User Story 4** → Read content works (Phase 6) — AI agent integration enabled
6. **+ User Story 5** → Local search works (Phase 7) — differentiator feature
7. **+ User Story 6** → Sharing info works (Phase 8) — full feature set
8. **Polish** → Production-ready (Phase 9)

### Full Sequential Order

For a single-threaded executor (LLM agent), the recommended task order is:

```
T001 → T002 → T003,T004 → T005–T010 → T011–T015 → T016 → T017 → T018
→ T019–T021 → T022 → T023 → T024 → T025
→ T026–T027 → T028 → T029 → T030
→ T031–T032 → T033 → T034
→ T035–T036 → T037 → T038
→ T039–T043 → T044 → T045 → T046 → T047 → T048 → T049
→ T050–T052 → T053 → T054 → T055 → T056
→ T057–T059 → T060 → T061
```

---

## Notes

- **[P] tasks** = different files, no dependencies on incomplete tasks in the same phase
- **[Story] label** maps each task to its specific user story for traceability
- **TDD is NON-NEGOTIABLE** (constitution Principle VI): write test → verify it fails → implement → verify it passes
- Each user story is independently completable and testable at its checkpoint
- Commit after each task or logical group (Conventional Commits: `test:`, `feat:`, `refactor:`)
- All Dropbox SDK calls MUST be mocked in unit tests (use `unittest.mock`)
- `--json` and `--verbose` flags must work on every command from the start (global options in app.py)
- Stop at any checkpoint to validate the story independently before proceeding
