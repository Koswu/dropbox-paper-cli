# Research: Dropbox Paper CLI v1.0

**Date**: 2025-07-18
**Feature**: 001-paper-cli-v1

## R1: Dropbox Python SDK — API Surface & Patterns

**Decision**: Use the `dropbox` Python package (PyPI) as the sole SDK dependency for all Dropbox API interactions.

**Rationale**: The official SDK provides typed wrappers for all required API endpoints (files, sharing, Paper export), built-in OAuth2 flow support including PKCE, and cursor-based pagination. It is actively maintained and is the only first-party Python SDK.

**Alternatives Considered**:
- Raw HTTP requests via `httpx` — rejected because the SDK already handles serialization, deserialization, retry headers, and the Stone data types. Reimplementing would violate Principle VII (Simplicity).
- Third-party wrappers (e.g., `dropboxdrivefs`) — rejected because they add an abstraction layer with no benefit for our use case, and they lag behind the official SDK.

**Key Findings**:
- **Client instantiation**: `dropbox.Dropbox(oauth2_access_token=...) ` or `dropbox.Dropbox(oauth2_refresh_token=..., app_key=...)` for auto-refresh.
- **File operations**: `files_list_folder`, `files_list_folder_continue`, `files_get_metadata`, `files_move_v2`, `files_copy_v2`, `files_delete_v2`, `files_create_folder_v2`.
- **Paper content export**: `files_export(path)` returns markdown content for `.paper` files. This is the correct API — NOT `files_download`.
- **Sharing links**: `sharing_create_shared_link_with_settings` and `sharing_list_shared_links`.
- **Shared folder info**: `sharing_get_folder_metadata`, `sharing_list_folder_members`, `sharing_list_folder_members_continue`.
- **Metadata types**: `dropbox.files.FileMetadata`, `dropbox.files.FolderMetadata` — use `isinstance()` to distinguish.
- **Error classes**: `dropbox.exceptions.ApiError`, `dropbox.exceptions.AuthError`, `dropbox.exceptions.HttpError`, `dropbox.exceptions.BadInputError`.
- **Rate limiting**: Detected via `ApiError` with tag inspection; `Retry-After` header available on 429 responses.
- **Cursor-based pagination**: `files_list_folder` returns a `ListFolderResult` with `.has_more` and `.cursor`. Save cursor between runs for incremental sync via `files_list_folder_continue`.

---

## R2: OAuth2 PKCE Flow — Dropbox SDK Support

**Decision**: Use `DropboxOAuth2FlowNoRedirect` with `use_pkce=True` and `token_access_type='offline'` as the primary auth flow.

**Rationale**: The Dropbox Python SDK has built-in PKCE support — no manual code_verifier/code_challenge generation needed. The `NoRedirect` variant is purpose-built for CLI tools: the user visits a URL, copies an authorization code, and pastes it back. The `'offline'` access type provides a refresh token for long-lived sessions.

**Alternatives Considered**:
- `DropboxOAuth2Flow` (redirect-based) — available as secondary flow for environments with a localhost callback server. Will support as FR-002 but not the primary path.
- Manual PKCE implementation with `httpx` — rejected because the SDK does this correctly out of the box.
- Device Code flow — not supported by Dropbox API.

**Key Findings**:
- **Primary flow (PKCE + NoRedirect)**:
  ```python
  auth_flow = DropboxOAuth2FlowNoRedirect(
      consumer_key=APP_KEY,
      use_pkce=True,
      token_access_type='offline'
  )
  url = auth_flow.start()
  # User visits URL, copies code
  result = auth_flow.finish(code)
  # result.access_token, result.refresh_token, result.expires_in, result.account_id
  ```
- **Token refresh**: Instantiate client with `oauth2_refresh_token` + `app_key` — SDK auto-refreshes transparently.
- **Token storage**: JSON file at `~/.dropbox-paper-cli/tokens.json` with `0600` permissions. Directory at `0700`.
- **Token format**: `{ access_token, refresh_token, expires_at, account_id, uid }`.
- **Atomic writes**: Write to temp file, then `os.rename()` to avoid corruption on interrupt.
- **No special Dropbox app console settings** needed for PKCE — the SDK handles it when `consumer_secret` is omitted.

---

## R3: Typer CLI Framework — Subcommand Groups & Global Options

**Decision**: Use Typer with `app.add_typer()` for command groups (`auth`, `files`, `cache`, `sharing`) and `@app.callback()` for global options (`--json`, `--verbose`).

**Rationale**: Typer's subcommand grouping maps directly to the spec's FR-001A grouped structure. The callback mechanism provides a clean way to inject global options without decorating every command.

**Alternatives Considered**:
- Click directly — Typer is built on Click and provides type-hint-driven command definitions that reduce boilerplate. The extra abstraction cost is minimal.
- argparse — rejected per constitution (Typer is mandated in Technical Constraints).
- Rich-click — adds theming but not subcommand grouping; unnecessary complexity for v1.

**Key Findings**:
- **Command group pattern**: Each group is a separate `typer.Typer()` instance in its own module, added to the main app via `app.add_typer(auth_app, name="auth", help="Authentication commands")`.
- **Global options via callback**:
  ```python
  @app.callback()
  def main(
      json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
      verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose diagnostics to stderr"),
  ):
      ctx = typer.get_context()  # or use state object
  ```
- **Error handling**: Wrap command logic in try/except, catch domain exceptions, format as JSON or human-readable based on `--json` flag, write to stderr, `raise typer.Exit(code=N)`.
- **Exit code convention**: 0=success, 1=general error, 2=auth error, 3=not-found error, 4=validation error, 5=network/rate-limit error.
- **Testing**: `typer.testing.CliRunner` for invoking commands in pytest; captures stdout, stderr, and exit code.

---

## R4: SQLite Local Metadata Cache — Schema & FTS5

**Decision**: Use Python's built-in `sqlite3` module with WAL mode, a `metadata` table for file/folder entries, a `sync_state` table for cursor tracking, and an FTS5 virtual table (`metadata_fts`) for keyword search.

**Rationale**: The built-in `sqlite3` module avoids external dependencies (Principle VII). FTS5 provides sub-second keyword search across 10,000+ items. WAL mode enables better concurrent access. Triggers keep the FTS index in sync with the metadata table automatically.

**Alternatives Considered**:
- SQLAlchemy ORM — rejected per Principle VII (Simplicity); the schema is simple enough for raw SQL.
- LIKE queries without FTS5 — rejected because performance degrades at scale; FTS5 gives O(1) lookups.
- External search tools (Whoosh, Tantivy) — rejected because FTS5 is built into SQLite.

**Key Findings**:
- **Schema**:
  - `metadata` table: `id TEXT PK, name TEXT, path_display TEXT UNIQUE, is_dir BOOLEAN, parent_id TEXT, size_bytes INTEGER, modified_at TEXT, rev TEXT`.
  - `sync_state` table: `key TEXT PK, cursor TEXT, last_sync_at TEXT, status TEXT`.
  - `metadata_fts` FTS5 virtual table: indexed on `name` and `path_display`, with trigram tokenizer for partial matching.
- **Triggers**: `AFTER INSERT/UPDATE/DELETE` on `metadata` to keep FTS index in sync.
- **Incremental sync**: Save Dropbox cursor in `sync_state`; on next sync, call `files_list_folder_continue(cursor)`. Handle `DeletedMetadata` entries by removing from local cache.
- **Cache corruption recovery**: Catch `sqlite3.DatabaseError` on open; delete and recreate the database file.
- **Connection management**: Single connection per CLI invocation, opened in `__enter__`, closed in `__exit__`.
- **Atomic sync**: Wrap entire sync operation in a transaction; commit only after all entries processed successfully.
- **Cache location**: `~/.dropbox-paper-cli/cache.db` (configurable).

---

## R5: Dropbox Paper URL Parsing

**Decision**: Implement a regex-based URL parser that extracts file IDs from the standard Dropbox Paper URL format.

**Rationale**: The spec mandates URL parsing (FR-050–FR-052) for a specific format. Regex is the simplest approach for a known URL structure.

**Alternatives Considered**:
- `urllib.parse` only — insufficient because the file ID is embedded in the URL path structure, not as a query parameter.
- A third-party URL parsing library — unnecessary for a single known format.

**Key Findings**:
- **URL format**: `https://www.dropbox.com/scl/fi/<file_id>/<name>?rlkey=...&dl=...`
- **Extraction pattern**: `r'https?://(?:www\.)?dropbox\.com/scl/fi/([^/]+)/.*'`
- **Implementation**: Accept either a raw ID or a URL in any file-related argument. Attempt URL parsing first; if it fails, treat the input as a raw ID.
- **Error case**: If a URL is provided but doesn't match the expected format, emit a clear error (FR-052).

---

## R6: Retry & Exponential Backoff Pattern

**Decision**: Implement a generic retry decorator/wrapper that handles transient Dropbox API errors (network errors, 429 rate limits, 5xx server errors) with exponential backoff, up to 3 retries.

**Rationale**: The spec requires auto-retry (FR-077–FR-079). A decorator pattern keeps retry logic separate from business logic (Principle II separation of concerns).

**Alternatives Considered**:
- `tenacity` library — provides a mature retry decorator but adds a dependency. Consider if implementation complexity warrants it. For v1, a simple custom retry wrapper is sufficient per Principle VII.
- SDK-level retry — the Dropbox SDK does NOT automatically retry on rate limits; the client must handle it.

**Key Findings**:
- **Retryable conditions**: `dropbox.exceptions.HttpError` (5xx), `ApiError` with rate-limit tag, network `ConnectionError`/`Timeout`.
- **Backoff formula**: `delay = base_delay * (2 ** attempt)` where `base_delay=1s`. Delays: 1s, 2s, 4s.
- **Retry-After header**: For 429 responses, prefer the server's `Retry-After` value over computed backoff.
- **Verbose logging**: When `--verbose` is set, log each retry attempt to stderr (FR-078).
- **Implementation**: A decorator `@with_retry(max_retries=3)` that wraps any function making SDK calls.

---

## R7: Python Project Tooling — uv, ruff, ty, pytest

**Decision**: Use `uv` for project management and dependency resolution, `ruff` for linting and formatting, `ty` for type checking, and `pytest` for testing.

**Rationale**: These are mandated by the constitution's Technical Constraints and the clarification session. `uv` is the fastest Python package manager. `ruff` combines linting and formatting in a single tool. `ty` provides standalone type checking.

**Alternatives Considered**: None — these are mandated.

**Key Findings**:
- **uv**: `uv init`, `uv add <dep>`, `uv run pytest`. Uses `pyproject.toml` for project metadata.
- **ruff**: Configure in `pyproject.toml` under `[tool.ruff]`. Enable `select = ["E", "F", "I", "W"]` at minimum. Format with `ruff format`.
- **ty**: Run with `ty check` for type checking. Configure strictness in `pyproject.toml` if supported.
- **pytest**: Convention: `tests/` mirrors `src/` structure. Use `conftest.py` for shared fixtures. Mock Dropbox SDK calls with `unittest.mock` or `pytest-mock`.
- **Project layout**: Use `src/dropbox_paper_cli/` layout for proper package isolation.
