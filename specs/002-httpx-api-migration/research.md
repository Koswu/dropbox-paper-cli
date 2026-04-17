# Research: Replace Dropbox SDK with Direct HTTP API + httpx

**Feature**: 002-httpx-api-migration
**Date**: 2025-07-15

## R-001: httpx AsyncClient as Dropbox HTTP Transport

**Decision**: Use a single `httpx.AsyncClient` instance shared across all service methods, with connection pooling enabled by default.

**Rationale**: httpx's `AsyncClient` provides built-in connection pooling, HTTP/2 support, configurable timeouts, and native async/await. A single shared client amortizes connection establishment cost across all API calls within a CLI command invocation. The Dropbox API uses three endpoint host patterns — all reachable via a single client with per-request URL construction.

**Alternatives Considered**:
- **aiohttp**: More mature async library but heavier API surface, no built-in timeout profiles, and requires manual session management. httpx has a requests-compatible API that's easier to reason about.
- **urllib3 + asyncio**: Would require wrapping synchronous calls in executors, defeating the purpose of native async.
- **Multiple AsyncClient instances**: Unnecessary overhead; a single client with connection pooling handles all three Dropbox API hosts efficiently.

**Key Implementation Details**:
- Client lifetime: created in `DropboxHttpClient.__init__()`, closed via `async with` or explicit `aclose()`
- Connection pool: httpx defaults (max_connections=100, max_keepalive_connections=20) are sufficient
- HTTP/2: Not needed — Dropbox API is HTTP/1.1; leave httpx at default HTTP/1.1

---

## R-002: Dropbox API Endpoint Architecture

**Decision**: Implement three request patterns matching Dropbox's three endpoint types, each with its own base URL and header conventions.

**Rationale**: The Dropbox HTTP API v2 uses three distinct endpoint types that differ in how parameters and data are transmitted:

### RPC Endpoints (19 methods)
- **Host**: `https://api.dropboxapi.com`
- **Content-Type**: `application/json`
- **Parameters**: JSON body
- **Response**: JSON body
- **Used by**: list_folder, get_metadata, move, copy, delete, create_folder, sharing operations, users/get_current_account

### Content-Download Endpoints (1 method)
- **Host**: `https://content.dropboxapi.com`
- **Content-Type**: (none or empty)
- **Parameters**: `Dropbox-API-Arg` header (JSON, HTTP-header-safe encoded)
- **Response**: Binary data in body, metadata in `Dropbox-API-Result` response header (JSON)
- **Used by**: files/export (Paper → Markdown)

### Content-Upload Endpoints (2 methods)
- **Host**: `https://content.dropboxapi.com`
- **Content-Type**: `application/octet-stream`
- **Parameters**: `Dropbox-API-Arg` header (JSON, HTTP-header-safe encoded)
- **Request body**: Raw binary content
- **Response**: JSON body with result metadata
- **Used by**: files/paper/create, files/paper/update

### All Endpoints
- **Authorization**: `Bearer <access_token>` header
- **Team namespace**: `Dropbox-API-Path-Root` header with JSON `{".tag": "root", "root": "<ns_id>"}`

**Alternatives Considered**:
- **Single unified request method**: Would obscure the important differences between endpoint types and make debugging harder.
- **Per-endpoint classes**: Over-engineering for 22 total endpoints; three helper methods (rpc/download/upload) in one client class is sufficient.

---

## R-003: All-Async Architecture with asyncio.run() Bridge

**Decision**: All service methods are `async def`. Each Typer CLI command calls `asyncio.run()` to bridge into the async layer.

**Rationale**: An all-async architecture avoids the "function coloring" problem within the service layer — every service can call every other service without sync/async adapters. The `asyncio.run()` boundary at the CLI layer is clean because Typer commands are naturally synchronous entry points that don't compose with each other.

**Implementation Pattern**:
```python
# CLI layer (sync entry point)
@files_app.command()
def list(ctx: typer.Context, path: str = ""):
    fmt = get_formatter(ctx)
    with safe_command(fmt):
        result = asyncio.run(_list_async(path))
        fmt.success(result)

async def _list_async(path: str) -> list[dict]:
    async with get_http_client() as client:
        svc = DropboxService(client)
        items = await svc.list_folder(path)
        return [item_to_dict(i) for i in items]
```

**Alternatives Considered**:
- **Hybrid sync/async**: Keep some services sync, only async for sync orchestrator. Rejected because it requires sync wrappers around async calls, creates confusing dual APIs, and doesn't leverage connection pooling for sequential commands.
- **anyio**: Cross-framework compatibility not needed; we target only asyncio.

---

## R-004: Token Refresh with asyncio.Lock + Double-Check

**Decision**: Use `asyncio.Lock` with double-check pattern for concurrent 401 handling. The lock is held by the HTTP client instance, not per-request.

**Rationale**: During concurrent async operations (e.g., sync with 20 parallel requests), multiple tasks may receive 401 simultaneously when the access token expires. Without coordination, all 20 tasks would attempt to refresh the token. The double-check pattern ensures exactly one refresh per expiry cycle:

```python
async def _handle_401(self):
    async with self._refresh_lock:
        # Double-check: another task may have already refreshed
        if not self._token.is_expired:
            return  # Token was refreshed by another task
        new_token = await self._refresh_token()
        self._token = new_token
        self._persist_token(new_token)
```

**Alternatives Considered**:
- **No coordination (refresh on every 401)**: Would cause redundant refreshes and potential race conditions with the token file.
- **asyncio.Event**: More complex signaling without the automatic mutual exclusion the Lock provides.
- **Token pre-refresh (refresh before expiry)**: Adds complexity and requires expiry timestamp to be accurate; not worth it for a CLI tool with short-lived sessions.

---

## R-005: Async Retry with Exponential Backoff

**Decision**: Rewrite `@with_retry()` as an async decorator that handles httpx-specific exceptions and respects `Retry-After` headers.

**Rationale**: The current retry decorator catches `dropbox.exceptions.HttpError` and `InternalServerError`. The new version must catch `httpx.HTTPStatusError` (for 429, 500, 503), `httpx.ConnectError`, `httpx.ReadTimeout`, and `httpx.ConnectTimeout`. The `Retry-After` header from 429 responses overrides the exponential backoff delay.

**Retryable Conditions**:
| Condition | Detection | Delay |
|-----------|-----------|-------|
| Rate limited (429) | `response.status_code == 429` | `Retry-After` header value (seconds) |
| Server error (500, 503) | `response.status_code in {500, 503}` | Exponential: `base * 2^attempt` |
| Connection error | `httpx.ConnectError` | Exponential: `base * 2^attempt` |
| Timeout | `httpx.ReadTimeout`, `httpx.ConnectTimeout` | Exponential: `base * 2^attempt` |

**Non-retryable**: 400, 401 (handled by token refresh), 403, 404, 409 (Dropbox API-specific errors).

**Alternatives Considered**:
- **tenacity library**: Full-featured retry library, but adds an unnecessary dependency for a decorator that's <40 lines of code. Constitution Principle VII (Simplicity) favors in-house.
- **httpx transport-level retry**: httpx doesn't have built-in retry; it must be done at the application layer.

---

## R-006: Timeout Profiles

**Decision**: Two named timeout profiles applied per-request based on endpoint type.

**Rationale**: Metadata/RPC operations are fast (small JSON payloads) and should fail quickly on timeout. Content operations (Paper export, create, update) involve larger payloads and need longer read timeouts.

| Profile | Connect | Read | Pool | Applied To |
|---------|---------|------|------|-----------|
| `METADATA` | 5s | 5s | 5s | All RPC endpoints, OAuth2 token endpoint |
| `CONTENT` | 5s | 30s | 5s | Content-download (export), content-upload (create, update) |

**Implementation**: Use `httpx.Timeout` objects passed per-request via the `timeout` parameter, not as client defaults. This allows the single shared client to use different timeouts per call.

**Alternatives Considered**:
- **Single timeout for all requests**: Would either be too short for content operations or too lenient for metadata calls.
- **Per-endpoint configurable timeouts**: Over-engineering; two profiles cover all current use cases.

---

## R-007: Sync Orchestrator Migration (ThreadPoolExecutor → asyncio)

**Decision**: Replace `ThreadPoolExecutor` + `Queue` with `asyncio.gather()` + `asyncio.Semaphore(20)` for the sync orchestrator.

**Rationale**: The current sync orchestrator uses `ThreadPoolExecutor(max_workers=concurrency)` with per-thread Dropbox clients (via `dbx.clone(session=dropbox.create_session())`). With all-async, this becomes:
- A single `AsyncClient` shared by all coroutines (connection pooling handles concurrency)
- `asyncio.Semaphore(concurrency)` limits concurrent in-flight requests to avoid rate limiting
- `asyncio.gather()` runs folder-level tasks concurrently
- No per-worker client creation; no thread-safety concerns

**Migration Mapping**:
| Current (threads) | New (async) |
|-------------------|-------------|
| `ThreadPoolExecutor(max_workers=N)` | `asyncio.Semaphore(N)` |
| `Queue()` for entry passing | Direct `await` / return values |
| `dbx.clone(session=...)` per worker | Single shared `AsyncClient` |
| `concurrent.futures.as_completed()` | `asyncio.gather(*tasks)` |
| `_SENTINEL` object for completion | Coroutine natural return |
| `conn.commit()` every 500 items | Same batched commits (SQLite is sync, called from async via brief sync blocks) |

**SQLite Access Pattern**: SQLite operations remain synchronous. Since they're fast (local I/O), they can be called directly from async code without blocking the event loop significantly. If profiling shows contention, `asyncio.to_thread()` can wrap DB calls, but this is not expected for a CLI tool.

**Alternatives Considered**:
- **asyncio.TaskGroup** (Python 3.11+): Provides structured concurrency with automatic cancellation. Good candidate but `gather()` is simpler for the "fan out, collect all" pattern used here. TaskGroup's stricter error propagation could cancel healthy tasks when one folder fails — undesirable for sync.
- **Keep ThreadPoolExecutor**: Would work but wastes the async architecture and doesn't benefit from connection pooling.

---

## R-008: Dropbox API Error Parsing

**Decision**: Parse Dropbox API error responses from JSON body and map to existing `AppError` hierarchy.

**Rationale**: The Dropbox API returns structured errors in JSON format. The response body for errors typically contains:
```json
{
  "error_summary": "path/not_found/...",
  "error": {
    ".tag": "path",
    "path": {
      ".tag": "not_found"
    }
  }
}
```

**Mapping**:
| HTTP Status | Dropbox Error | Maps To |
|-------------|--------------|---------|
| 400 | Bad request | `ValidationError` |
| 401 | Expired/invalid token | Token refresh → retry, or `AuthenticationError` |
| 403 | Insufficient permissions | `PermissionError` |
| 409 | Endpoint-specific error | Parse `error_summary` → `NotFoundError`, `ValidationError`, etc. |
| 429 | Rate limited | Retry with `Retry-After` |
| 500, 503 | Server error | Retry with backoff |

The 409 status code is Dropbox-specific: it signals an API-level error (not found, conflict, etc.) rather than an HTTP-level error. The `error_summary` string contains a path-like descriptor (e.g., `path/not_found/`) that can be parsed to determine the specific error type.

**Alternatives Considered**:
- **Raise raw httpx exceptions**: Loses the structured error information; existing CLI error handling depends on `AppError` subtypes.
- **Create new error types**: Unnecessary; the existing `NotFoundError`, `ValidationError`, `AuthenticationError`, `PermissionError`, `NetworkError` cover all Dropbox API error cases.

---

## R-009: OAuth2 Direct HTTP Implementation

**Decision**: Implement OAuth2 PKCE and Authorization Code flows via direct HTTP requests, replacing `DropboxOAuth2FlowNoRedirect`.

**Rationale**: The SDK's OAuth2 flow class is a thin wrapper around two HTTP endpoints. Reimplementing directly eliminates the last SDK dependency.

**Endpoints**:
1. **Authorization URL**: `https://www.dropbox.com/oauth2/authorize` (GET, browser redirect)
   - Parameters: `client_id`, `response_type=code`, `code_challenge` (PKCE), `code_challenge_method=S256`, `token_access_type=offline`
2. **Token Exchange**: `POST https://api.dropboxapi.com/oauth2/token`
   - Parameters: `grant_type=authorization_code`, `code`, `client_id`, `code_verifier` (PKCE) or `client_secret` (auth code flow)
3. **Token Refresh**: `POST https://api.dropboxapi.com/oauth2/token`
   - Parameters: `grant_type=refresh_token`, `refresh_token`, `client_id`

**PKCE Implementation**:
- Generate 32-byte random `code_verifier` (base64url, no padding)
- Compute `code_challenge = base64url(sha256(code_verifier))`
- All using Python stdlib (`secrets`, `hashlib`, `base64`)

**Alternatives Considered**:
- **authlib library**: Full OAuth2 client, but adds a heavy dependency for what amounts to two HTTP POST calls. Constitution Principle VII.
- **Keep SDK just for OAuth2**: Defeats the purpose of removing the dependency entirely.

---

## R-010: Observability — DEBUG-Level HTTP Logging

**Decision**: Log all HTTP requests at DEBUG level via Python's `logging` module. Visible only when `--verbose` is passed or `PAPER_LOG_LEVEL=DEBUG` is set.

**Rationale**: Direct HTTP calls lose the SDK's internal error context. DEBUG logging of every request/response provides the same (and better) diagnostic capability.

**Log Format**:
```
DEBUG dropbox_paper_cli.lib.http_client: POST https://api.dropboxapi.com/2/files/list_folder -> 200 (142ms)
DEBUG dropbox_paper_cli.lib.http_client: POST https://api.dropboxapi.com/oauth2/token -> 200 (89ms)
DEBUG dropbox_paper_cli.lib.http_client: POST https://api.dropboxapi.com/2/files/list_folder -> 429 (12ms) [retry in 1s]
```

**Implementation**:
- Use `logging.getLogger("dropbox_paper_cli.lib.http_client")`
- `--verbose` flag sets root logger to DEBUG level
- `PAPER_LOG_LEVEL` env var provides env-based control
- Log: method, full URL, status code, duration in ms
- On retry: additionally log retry delay and attempt number
- Request/response bodies are NOT logged (contain auth tokens and potentially large content)

**Alternatives Considered**:
- **httpx event hooks**: httpx supports `event_hooks` on the client for request/response logging. This is cleaner than wrapping each call but provides less control over log formatting. Decision: use event hooks for timing, but format logs ourselves.
- **structlog**: Structured logging library — overkill for a CLI tool. Python `logging` is sufficient.

---

## R-011: Model Migration (from_sdk → from_api)

**Decision**: Add `from_api(data: dict)` classmethods to `DropboxItem`, `MemberInfo`, `SharingInfo` alongside deprecating `from_sdk()`. Remove `from_sdk()` after all callers are migrated.

**Rationale**: The models currently construct from SDK objects (e.g., `dropbox.files.FileMetadata`). With direct HTTP, they construct from parsed JSON dictionaries. The JSON field names match the SDK attribute names (the SDK is auto-generated from the API spec), so the mapping is straightforward.

**JSON → Model Mapping** (example for DropboxItem):
```python
@classmethod
def from_api(cls, data: dict) -> "DropboxItem":
    tag = data.get(".tag", "file")
    return cls(
        id=data.get("id", ""),
        name=data.get("name", ""),
        path_display=data.get("path_display", ""),
        path_lower=data.get("path_lower", ""),
        type="folder" if tag == "folder" else "file",
        size=data.get("size"),
        server_modified=data.get("server_modified"),
        rev=data.get("rev"),
        content_hash=data.get("content_hash"),
    )
```

**Alternatives Considered**:
- **Pydantic models**: Type-safe JSON parsing, but adds a dependency and changes the model layer significantly. Existing dataclasses + dict parsing is sufficient.
- **TypedDict for API responses**: Provides type hints but no runtime validation; dataclasses with `from_api()` give both.

---

## R-012: Dependency Changes

**Decision**: Remove `dropbox>=12.0.0` from dependencies. Add `httpx>=0.27.0`.

**Rationale**: httpx 0.27+ provides stable AsyncClient, connection pooling, and timeout APIs. The `dropbox` package pulls in `requests`, `urllib3`, `stone`, and other transitive dependencies. Removing it significantly shrinks the dependency tree.

**pyproject.toml Changes**:
```toml
# Before
dependencies = [
    "typer>=0.15.0",
    "dropbox>=12.0.0",
    "textual>=3.0.0",
]

# After
dependencies = [
    "typer>=0.15.0",
    "httpx>=0.27.0",
    "textual>=3.0.0",
]
```

**Dev dependency addition**: `pytest-httpx>=0.30.0` for test mocking of httpx requests (provides `httpx_mock` fixture that integrates with pytest-asyncio).

**Alternatives Considered**:
- **httpx[http2]**: HTTP/2 support via h2 package. Not needed — Dropbox API is HTTP/1.1.
- **Keep dropbox as optional**: Adds maintenance burden for no benefit; clean break is better.
