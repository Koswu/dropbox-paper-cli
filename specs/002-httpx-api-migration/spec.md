# Feature Specification: Replace Dropbox SDK with Direct HTTP API + httpx

**Feature Branch**: `002-httpx-api-migration`  
**Created**: 2025-07-15  
**Status**: Draft  
**Input**: User description: "Replace Dropbox Python SDK with direct HTTP API + httpx (async)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - All Existing CLI Commands Continue to Work (Priority: P1)

As a user of the `paper` CLI, I want all existing commands (browse, organize, read, write, search, share) to continue working identically after the SDK is removed, so that the migration is invisible to me and I experience no disruption.

**Why this priority**: This is the foundational requirement. If existing behavior breaks, the migration fails regardless of any performance improvements. Every CLI user depends on these operations working reliably.

**Independent Test**: Can be fully tested by running every existing CLI command (`paper files list`, `paper files move`, `paper files copy`, `paper files delete`, `paper files create-folder`, `paper files read`, `paper files create`, `paper files write`, `paper sharing info`, `paper sharing link`, `paper cache sync`, `paper search`) and verifying identical output and behavior against the current SDK-based implementation. (Shorthand aliases like `paper ls`, `paper mv`, etc. are used in acceptance scenarios below for brevity.)

**Acceptance Scenarios**:

1. **Given** a user is authenticated, **When** they run `paper ls /some-folder`, **Then** they see the same file and folder listing as with the SDK-based implementation
2. **Given** a user is authenticated, **When** they run `paper cat /path/to/document.paper`, **Then** they see the exported Markdown content of the Paper document
3. **Given** a user is authenticated, **When** they run `paper create /path/to/new.paper --content "# Hello"`, **Then** a new Paper document is created and the result (URL, path, file ID) is displayed
4. **Given** a user is authenticated, **When** they run `paper update /path/to/doc.paper --content "# Updated"`, **Then** the document is updated and the new revision is displayed
5. **Given** a user is authenticated, **When** they run `paper mv /old/path /new/path`, **Then** the item is moved and the new metadata is displayed
6. **Given** a user is authenticated, **When** they run `paper share /path/to/item`, **Then** sharing information (link, members) is displayed correctly

---

### User Story 2 - Authentication Flows Work Without the SDK (Priority: P1)

As a new or returning user, I want the OAuth2 login flow (both PKCE and Authorization Code) to work correctly without the Dropbox SDK, so that I can authenticate and use the CLI.

**Why this priority**: Authentication is a prerequisite for all other functionality. If users cannot log in or their tokens cannot refresh, the entire CLI is unusable.

**Independent Test**: Can be fully tested by running `paper auth login`, completing the browser-based OAuth2 flow, verifying the token is stored securely, and then confirming that subsequent commands work. Also testable by letting an access token expire and verifying automatic refresh occurs seamlessly.

**Acceptance Scenarios**:

1. **Given** a user is not authenticated, **When** they run `paper auth login`, **Then** they receive an authorization URL, can complete the browser flow, paste the code, and obtain valid tokens
2. **Given** a user has a valid refresh token but an expired access token, **When** they run any CLI command, **Then** the access token is refreshed automatically and the command succeeds without user intervention
3. **Given** a user is in a team account, **When** they authenticate, **Then** the root namespace is detected and persisted so team files are accessible
4. **Given** a user runs `paper auth logout`, **When** the command completes, **Then** stored tokens are securely deleted

---

### User Story 3 - Sync Operations Are Faster with Async Concurrency (Priority: P2)

As a user with a large Dropbox Paper workspace (hundreds or thousands of documents), I want the `paper sync` command to complete faster by leveraging async concurrency, so that my local metadata cache is refreshed efficiently.

**Why this priority**: Sync performance is a primary motivation for this migration. Users with large workspaces currently experience slow sync due to synchronous HTTP calls. This story delivers the core performance benefit.

**Independent Test**: Can be tested by running `paper sync` on a workspace with at least 100 documents and measuring completion time. The async implementation should show measurable improvement over the current threading-based approach, especially on incremental syncs.

**Acceptance Scenarios**:

1. **Given** a user has never synced, **When** they run `paper sync`, **Then** a full sync completes and the local cache is populated with all metadata
2. **Given** a user has previously synced, **When** they run `paper sync`, **Then** an incremental sync detects additions, modifications, and deletions since the last sync
3. **Given** a workspace with 500+ items, **When** the user runs `paper sync`, **Then** the operation completes at least 30% faster than the previous SDK approach, using up to 20 concurrent async requests (configurable semaphore)
4. **Given** a sync is in progress, **When** a transient network error occurs on one folder, **Then** that folder is retried and other folders continue syncing without interruption

---

### User Story 4 - Robust Error Handling and Retry Behavior (Priority: P2)

As a user on an unreliable network, I want the CLI to handle transient HTTP errors gracefully (timeouts, rate limits, server errors) with automatic retries and clear error messages, so that temporary issues do not cause commands to fail unnecessarily.

**Why this priority**: Direct HTTP API calls give the application full control over error handling, timeouts, and retry behavior — a key motivation for the migration. Users benefit from more reliable operations.

**Independent Test**: Can be tested by simulating network errors (connection timeouts, 429 rate limit responses, 500 server errors) and verifying that retries occur with backoff and that user-facing error messages are clear and actionable.

**Acceptance Scenarios**:

1. **Given** a Dropbox API call returns a 429 (rate limited) response, **When** the retry logic activates, **Then** the request is retried after the indicated backoff period and succeeds
2. **Given** a Dropbox API call returns a 500/503 server error, **When** the retry logic activates, **Then** the request is retried with exponential backoff (up to 3 attempts)
3. **Given** a Dropbox API call times out, **When** the configured timeout elapses, **Then** the request is retried and the user sees a clear error if all retries fail
4. **Given** a Dropbox API returns a 401 (expired token), **When** the client detects this, **Then** it refreshes the access token and retries the original request transparently

---

### User Story 5 - Dropbox SDK Dependency Is Fully Removed (Priority: P3)

As a project maintainer, I want the `dropbox` SDK package completely removed from the dependency tree and replaced with `httpx`, so that the project has fewer transitive dependencies and full control over HTTP behavior.

**Why this priority**: Dependency hygiene is important for maintainability but does not directly affect user-facing behavior. It is a natural outcome of the other stories being completed.

**Independent Test**: Can be verified by checking `pyproject.toml` for the absence of the `dropbox` dependency, presence of `httpx`, and running `pip list` to confirm the `dropbox` package is not installed. All tests must pass with only `httpx` as the HTTP library.

**Acceptance Scenarios**:

1. **Given** the migration is complete, **When** a maintainer inspects `pyproject.toml`, **Then** `dropbox` is not listed as a dependency and `httpx` is listed instead
2. **Given** the migration is complete, **When** the full test suite runs, **Then** all existing tests pass (with test mocks updated to mock HTTP responses instead of SDK objects)
3. **Given** the migration is complete, **When** a developer searches the codebase for `import dropbox`, **Then** zero results are found

---

### Edge Cases

- What happens when the Dropbox API returns an unexpected JSON structure or missing fields? The `from_api()` factory methods MUST catch `KeyError`/`TypeError` from malformed JSON and raise `ValidationError` with a message including the missing field name and the first 200 characters of the raw response, rather than propagating unhandled exceptions.
- What happens when a token refresh fails (e.g., refresh token revoked)? The user should see a clear message instructing them to re-authenticate.
- What happens during concurrent async requests if the access token expires mid-batch? The HTTP client MUST use an `asyncio.Lock` with a double-check pattern: the first task to receive a 401 acquires the lock and refreshes the token; concurrent tasks wait on the lock, then verify the token was already refreshed before retrying with the new token. Only one refresh occurs per expiry cycle.
- What happens if the Dropbox API rate-limits specific endpoints differently? The retry logic should respect per-response `Retry-After` headers.
- What happens when a Paper document export returns unexpected content encoding? The client MUST attempt UTF-8 decoding; if decoding fails, raise `ValidationError` with the encoding error details and the first 200 bytes of raw content for diagnosis.
- What happens during sync when a folder is deleted server-side between the top-level listing and the folder's recursive listing? The error should be handled and the sync should continue.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST replace the `dropbox` Python SDK dependency with `httpx` for all HTTP communication with the Dropbox API
- **FR-002**: System MUST implement OAuth2 PKCE flow by making direct HTTP requests to the Dropbox OAuth2 endpoints (`https://www.dropbox.com/oauth2/authorize` and `https://api.dropboxapi.com/oauth2/token`)
- **FR-003**: System MUST implement OAuth2 Authorization Code flow via direct HTTP requests for environments that use app secrets
- **FR-004**: System MUST automatically refresh expired access tokens using the stored refresh token via the token endpoint, without user intervention; concurrent 401 responses MUST be coordinated via an `asyncio.Lock` with double-check pattern so that only one refresh occurs per expiry cycle
- **FR-005**: System MUST implement a centralized async HTTP client layer (using httpx `AsyncClient`) that encapsulates all Dropbox API communication, including headers, authentication, content upload/download, and error parsing — all service methods MUST be `async def`
- **FR-006**: System MUST support all current file and folder operations via direct Dropbox HTTP API calls: list folder (with pagination), get metadata, create folder, move, copy, delete
- **FR-007**: System MUST support Paper document operations via direct API calls: export (as Markdown), create (with import format), update (with revision and policy)
- **FR-008**: System MUST support sharing operations via direct API calls: create/get sharing links, get shared folder metadata, list folder members (with pagination)
- **FR-009**: System MUST implement shared link URL resolution via the sharing API endpoint
- **FR-010**: System MUST support team namespace detection and path root configuration via direct API calls to the users/get_current_account endpoint
- **FR-011**: System MUST implement retry logic for transient HTTP errors (429, 500, 503, connection errors, timeouts) with exponential backoff and respect for `Retry-After` headers
- **FR-012**: System MUST use `asyncio.run()` at each CLI command entry point as the sync/async boundary; the sync orchestrator replaces the current thread-pool approach with `asyncio.gather()` or equivalent async concurrency, throttled by an `asyncio.Semaphore(20)` (configurable via the existing `--concurrency` CLI flag) to match the current proven concurrency level and avoid triggering API rate limits
- **FR-013**: System MUST provide predefined timeout profiles for all HTTP requests: metadata/RPC endpoints default to `connect=5s, read=5s`; content-download and content-upload endpoints default to `connect=5s, read=30s` (compile-time constants; runtime override is not required for this migration)
- **FR-014**: System MUST use connection pooling to efficiently reuse HTTP connections across multiple API calls
- **FR-015**: System MUST preserve the existing token file format and storage mechanism (JSON file with 0600 permissions, atomic writes) so that users do not need to re-authenticate after the migration
- **FR-016**: System MUST maintain all existing error types (`NotFoundError`, `ValidationError`, `AuthenticationError`, `NetworkError`, `PermissionError`) and map HTTP response codes and Dropbox API error structures to these types
- **FR-017**: System MUST handle the Dropbox API's content-download endpoints (which return data in the response body with metadata in a special header) correctly
- **FR-018**: System MUST handle the Dropbox API's content-upload endpoints (which accept data in the request body with parameters in a special header) correctly
- **FR-019**: System MUST update the model layer to parse Dropbox API JSON responses directly instead of relying on SDK metadata objects
- **FR-020**: System MUST ensure all existing tests pass after migration, with test mocks updated from SDK object mocks to HTTP response mocks
- **FR-021**: System MUST log all HTTP requests at DEBUG level (method, URL, status code, duration) via Python's `logging` module; logs are hidden by default and visible when the user sets `PAPER_LOG_LEVEL=DEBUG` or passes `--verbose`

### Key Entities

- **HTTP Client**: The central component that manages authenticated communication with the Dropbox API, handling request construction, authentication headers, token refresh, retries, timeouts, and response parsing
- **Auth Token**: Persisted OAuth2 credentials (access token, refresh token, expiry, account ID, namespace IDs) stored in a local JSON file — format remains unchanged across the migration
- **API Response**: Parsed Dropbox HTTP API response containing metadata, content, or error information — replaces SDK-specific objects like `FileMetadata`, `FolderMetadata`, etc.
- **Dropbox Item**: Internal representation of a file or folder — currently constructed from SDK objects via `from_sdk()`, will be constructed from API JSON via a new factory method

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All existing CLI commands produce identical output and behavior after migration — zero user-visible regressions
- **SC-002**: The `dropbox` package is completely absent from the dependency tree; `httpx` is the sole HTTP library
- **SC-003**: Full sync of a workspace with 500+ items completes at least 30% faster than the current SDK-based implementation
- **SC-004**: All existing tests pass after migration (with updated mocks), maintaining current test coverage levels
- **SC-005**: Transient errors (429, 500, 503, connection errors, timeouts) are retried automatically with exponential backoff (up to 3 attempts) before surfacing an error to the user; `Retry-After` headers from 429 responses are respected
- **SC-006**: Token refresh occurs transparently — users are never prompted to re-authenticate due to expired access tokens (only if the refresh token itself is revoked)
- **SC-007**: Existing authenticated users can continue using the CLI after updating without needing to re-authenticate (token file compatibility preserved)
- **SC-008**: Sequential multi-step operations (e.g., listing a folder then reading a document) complete within timeout bounds — metadata calls respond within 5s and content operations within 30s under normal conditions

## Assumptions

- Users have Python 3.12 or later installed, which provides full `asyncio` support needed for `httpx` async operations
- The Dropbox HTTP API endpoints used by this project are stable and publicly documented at https://www.dropbox.com/developers/documentation/http/documentation
- The existing token file format (`~/.config/dropbox-paper-cli/tokens.json`) is sufficient for storing all OAuth2 credentials needed for direct API communication — no schema change is required
- Existing integration tests that hit the real Dropbox API will continue to work since the API endpoints are the same; only the transport layer changes
- The `httpx` library is production-ready and provides the async capabilities, connection pooling, and timeout controls needed for this migration
- The Dropbox API uses standard HTTP status codes for error signaling (401 for auth errors, 409 for endpoint-specific errors, 429 for rate limits, 500/503 for server errors)
- The current CLI's synchronous command execution model (via Typer) is compatible with running async httpx calls internally; each CLI command entry point calls `asyncio.run()` to bridge into the all-async service layer
- Team namespace detection logic (root vs. home namespace) works identically whether accessed via SDK or direct API, since the SDK is just a wrapper around the same API

## Clarifications

### Session 2026-04-18

- Q: Should the HTTP client use AsyncClient for all operations (all-async) or only for the sync orchestrator (hybrid)? → A: All-async — single AsyncClient for all operations, all service methods are `async def`, `asyncio.run()` at each CLI command entry point
- Q: What mechanism coordinates concurrent token refresh when multiple async tasks receive 401 simultaneously? → A: `asyncio.Lock` with double-check pattern — first task acquires lock and refreshes, others wait then retry with new token
- Q: What is the maximum async concurrency limit for the sync orchestrator? → A: `asyncio.Semaphore(20)` (configurable), matching the current thread pool size to avoid rate-limit spikes
- Q: What are the default timeout values for HTTP requests? → A: Metadata/RPC endpoints: `connect=5s, read=5s`; content-download/upload endpoints: `connect=5s, read=30s`
- Q: Should the HTTP client layer include observability/logging? → A: DEBUG-level request/response logging (method, URL, status code, duration) for all API calls; visible only via `--verbose` flag or `PAPER_LOG_LEVEL=DEBUG` env var
