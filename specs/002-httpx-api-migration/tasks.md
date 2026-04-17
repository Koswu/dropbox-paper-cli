# Tasks: Replace Dropbox SDK with Direct HTTP API + httpx

**Input**: Design documents from `/specs/002-httpx-api-migration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (rpc-endpoints.md, content-endpoints.md, oauth2-endpoints.md), quickstart.md

**Tests**: Included — the spec requires all existing tests to pass with updated mocks (SC-004, FR-020), and the current codebase already has comprehensive unit tests that must be migrated from SDK mocks to HTTP response mocks.

**Organization**: Tasks are grouped by user story (from spec.md priorities P1→P3). Each user story phase is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4, US5)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependency changes, project configuration, and new module scaffolding

- [ ] T001 Update dependencies in pyproject.toml: replace `dropbox>=12.0.0` with `httpx>=0.27.0`, add `pytest-httpx>=0.30.0` to dev dependencies
- [ ] T002 Run `uv sync --dev` to regenerate uv.lock with new dependencies and verify environment
- [ ] T003 Create empty module file src/dropbox_paper_cli/lib/http_client.py with module docstring and `__all__` placeholder
- [ ] T004 Create empty test file tests/unit/lib/test_http_client.py with module docstring and pytest-asyncio imports

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core HTTP client layer, async retry, timeout profiles, error mapping — everything services depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. All services depend on `DropboxHttpClient` and async `@with_retry`.

### HTTP Client Core

- [ ] T005 Implement `METADATA_TIMEOUT` and `CONTENT_TIMEOUT` constants in src/dropbox_paper_cli/lib/http_client.py using `httpx.Timeout(5.0, connect=5.0, read=5.0, pool=5.0)` and `httpx.Timeout(30.0, connect=5.0, read=30.0, pool=5.0)` per R-006
- [ ] T006 Implement `encode_api_arg()` helper in src/dropbox_paper_cli/lib/http_client.py for encoding Dropbox-API-Arg header JSON with non-ASCII escaping per content-endpoints.md contract
- [ ] T007 Implement `DropboxHttpClient.__init__()` in src/dropbox_paper_cli/lib/http_client.py accepting `token: AuthToken` and `app_key: str`, initializing `_refresh_lock: asyncio.Lock`, `_logger`, `_client: httpx.AsyncClient | None` per data-model.md entity spec
- [ ] T008 Implement `DropboxHttpClient.__aenter__()` and `__aexit__()` async context manager in src/dropbox_paper_cli/lib/http_client.py to create/close `httpx.AsyncClient` with connection pooling defaults per R-001
- [ ] T009 Implement `DropboxHttpClient._auth_headers()` in src/dropbox_paper_cli/lib/http_client.py returning `Authorization: Bearer` header and optional `Dropbox-API-Path-Root` for team namespace per rpc-endpoints.md common headers
- [ ] T010 Implement `DropboxHttpClient._raise_for_api_error()` in src/dropbox_paper_cli/lib/http_client.py parsing Dropbox error JSON (409 `error_summary` patterns, 400, 403) and mapping to `NotFoundError`, `ValidationError`, `PermissionError`, `AuthenticationError` per R-008 and rpc-endpoints.md error mapping table
- [ ] T011 Implement `DropboxHttpClient._handle_401()` with asyncio.Lock double-check pattern in src/dropbox_paper_cli/lib/http_client.py per R-004: acquire lock, check if token already refreshed, call `_refresh_token()` if not, update `_token` and persist
- [ ] T012 Implement `DropboxHttpClient._refresh_token()` in src/dropbox_paper_cli/lib/http_client.py: POST to `https://api.dropboxapi.com/oauth2/token` with `grant_type=refresh_token` per oauth2-endpoints.md token refresh contract, returning updated AuthToken (keep existing refresh_token, account_id, uid, namespace IDs)
- [ ] T013 Implement DEBUG-level HTTP request logging in `DropboxHttpClient._request()` in src/dropbox_paper_cli/lib/http_client.py using `logging.getLogger("dropbox_paper_cli.lib.http_client")` — log method, URL, status code, duration in ms; on retry log delay and attempt per R-010
- [ ] T014 Implement `DropboxHttpClient._request()` low-level method in src/dropbox_paper_cli/lib/http_client.py: attach auth headers, execute via `self._client`, handle 401 (call `_handle_401` then retry once), raise for non-2xx via `_raise_for_api_error`, include DEBUG logging per T013
- [ ] T015 Implement `DropboxHttpClient.rpc()` in src/dropbox_paper_cli/lib/http_client.py: POST to `https://api.dropboxapi.com/2/{endpoint}` with JSON body, `Content-Type: application/json`, using `METADATA_TIMEOUT` default, return parsed JSON dict per rpc-endpoints.md contract
- [ ] T016 Implement `DropboxHttpClient.content_download()` in src/dropbox_paper_cli/lib/http_client.py: POST to `https://content.dropboxapi.com/2/{endpoint}` with `Dropbox-API-Arg` header (via `encode_api_arg`), parse `Dropbox-API-Result` response header as JSON metadata, return `(body_bytes, metadata_dict)` per content-endpoints.md download contract
- [ ] T017 Implement `DropboxHttpClient.content_upload()` in src/dropbox_paper_cli/lib/http_client.py: POST to `https://content.dropboxapi.com/2/{endpoint}` with `Dropbox-API-Arg` header, `Content-Type: application/octet-stream`, raw bytes body, return parsed JSON response dict per content-endpoints.md upload contract

### Async Retry Decorator

- [ ] T018 Rewrite `@with_retry()` as async decorator in src/dropbox_paper_cli/lib/retry.py: replace `dropbox.exceptions` imports with `httpx` imports, change inner wrapper to `async def`, replace `time.sleep()` with `asyncio.sleep()`, detect retryable conditions (429 + Retry-After, 500/503, `httpx.ConnectError`, `httpx.ReadTimeout`, `httpx.ConnectTimeout`) per R-005 decision table

### Foundational Tests

- [ ] T019 [P] Write unit tests for `encode_api_arg()` in tests/unit/lib/test_http_client.py: ASCII-only JSON, non-ASCII character escaping, compact separators
- [ ] T020 [P] Write unit tests for `DropboxHttpClient.rpc()` in tests/unit/lib/test_http_client.py: successful JSON response, 409 error mapping to NotFoundError/ValidationError, auth header inclusion, team namespace path-root header
- [ ] T021 [P] Write unit tests for `DropboxHttpClient.content_download()` in tests/unit/lib/test_http_client.py: verify `Dropbox-API-Arg` header encoding, `Dropbox-API-Result` header parsing, binary body return, CONTENT_TIMEOUT applied
- [ ] T022 [P] Write unit tests for `DropboxHttpClient.content_upload()` in tests/unit/lib/test_http_client.py: verify `Dropbox-API-Arg` header, `application/octet-stream` content-type, raw body, JSON response parsing
- [ ] T023 [P] Write unit tests for `_handle_401()` double-check pattern in tests/unit/lib/test_http_client.py: single refresh on concurrent 401s, token update propagation, `AuthenticationError` on `invalid_grant`
- [ ] T024 [P] Write unit tests for DEBUG logging in tests/unit/lib/test_http_client.py: verify log format (method, URL, status, duration ms), no logging at INFO level, retry logging includes delay
- [ ] T025 [P] Rewrite tests/unit/lib/test_retry.py: replace all `dropbox.exceptions` mock fixtures with `httpx.HTTPStatusError`/`httpx.ConnectError`/`httpx.ReadTimeout` mocks, make test functions `async def` with `@pytest.mark.asyncio`, test 429 with `Retry-After` header, test exponential backoff for 500/503

**Checkpoint**: Foundation ready — `DropboxHttpClient` and async `@with_retry` are complete and tested. All user story implementation can now begin.

---

## Phase 3: User Story 1 — All Existing CLI Commands Continue to Work (Priority: P1) 🎯 MVP

**Goal**: Rewrite `DropboxService`, `SharingService`, and models to use `DropboxHttpClient` instead of Dropbox SDK. All existing CLI commands produce identical output.

**Independent Test**: Run every existing CLI command (`paper ls`, `paper mv`, `paper cp`, `paper rm`, `paper mkdir`, `paper cat`, `paper create`, `paper update`, `paper share`, `paper search`, `paper sync`) and verify identical output and behavior.

### Models — from_sdk() → from_api()

- [ ] T026 [P] [US1] Add `DropboxItem.from_api(data: dict)` classmethod in src/dropbox_paper_cli/models/items.py: parse `.tag` for type, map `id`, `name`, `path_display`, `path_lower`, `size`, `server_modified`, `rev`, `content_hash` from JSON dict per data-model.md field mapping table. Remove `from_sdk()` classmethod and all `import dropbox` references.
- [ ] T027 [P] [US1] Update `PaperCreateResult` construction in src/dropbox_paper_cli/models/items.py to parse from API JSON dict (`url`, `result_path`, `file_id`, `paper_revision`) — add `from_api()` if needed, remove any SDK object construction
- [ ] T028 [P] [US1] Update `PaperUpdateResult` construction in src/dropbox_paper_cli/models/items.py to parse from API JSON dict (`paper_revision`) — add `from_api()` if needed, remove any SDK object construction
- [ ] T029 [P] [US1] Add `MemberInfo.from_api(entry: dict)` classmethod in src/dropbox_paper_cli/models/sharing.py: parse `entry["user"]["account_id"]`, `entry["user"]["display_name"]`, `entry["user"]["email"]`, `entry["access_type"][".tag"]` per data-model.md field mapping. Remove `from_sdk()` and all `import dropbox` references.
- [ ] T030 [P] [US1] Add `SharingInfo.from_api(data: dict, members: list[MemberInfo] | None)` classmethod in src/dropbox_paper_cli/models/sharing.py: parse `shared_folder_id`, `name`, `path_display` from JSON dict. Remove `from_sdk()`.

### Model Tests

- [ ] T031 [P] [US1] Rewrite tests/unit/models/test_items.py: replace all `dropbox.files.FileMetadata`/`FolderMetadata` mock fixtures with plain dicts matching Dropbox API JSON schema from rpc-endpoints.md contract, test `from_api()` for files (with size/rev/content_hash), folders (tag=folder, no size), Paper documents (.paper extension)
- [ ] T032 [P] [US1] Rewrite tests/unit/models/test_sharing.py: replace all SDK mock objects with plain dicts matching sharing API JSON schema from rpc-endpoints.md contract, test `MemberInfo.from_api()` and `SharingInfo.from_api()` with member lists

### DropboxService Rewrite

- [ ] T033 [US1] Rewrite `DropboxService.__init__()` in src/dropbox_paper_cli/services/dropbox_service.py to accept `client: DropboxHttpClient` instead of `dropbox.Dropbox`. Remove all `import dropbox` statements.
- [ ] T034 [US1] Rewrite `DropboxService.list_folder()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.rpc("files/list_folder", {...})`, handle pagination via `files/list_folder/continue` with `has_more`/`cursor`, return `[DropboxItem.from_api(e) for e in entries]` per rpc-endpoints.md contract
- [ ] T035 [US1] Rewrite `DropboxService.get_metadata()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.rpc("files/get_metadata", {"path": path})`, return `DropboxItem.from_api(data)`
- [ ] T036 [P] [US1] Rewrite `DropboxService.move()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.rpc("files/move_v2", {"from_path": ..., "to_path": ..., "autorename": False})`, return `DropboxItem.from_api(data["metadata"])`
- [ ] T037 [P] [US1] Rewrite `DropboxService.copy()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.rpc("files/copy_v2", {"from_path": ..., "to_path": ..., "autorename": False})`, return `DropboxItem.from_api(data["metadata"])`
- [ ] T038 [P] [US1] Rewrite `DropboxService.delete()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.rpc("files/delete_v2", {"path": path})`, return `DropboxItem.from_api(data["metadata"])`
- [ ] T039 [P] [US1] Rewrite `DropboxService.create_folder()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.rpc("files/create_folder_v2", {"path": path, "autorename": False})`, return `DropboxItem.from_api(data["metadata"])`
- [ ] T040 [US1] Rewrite `DropboxService.export_paper()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.content_download("files/export", {"path": path})`, decode body bytes as UTF-8 for Markdown content, return content string and metadata per content-endpoints.md export contract
- [ ] T041 [US1] Rewrite `DropboxService.create_paper()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.content_upload("files/paper/create", {"path": path, "import_format": {".tag": fmt}}, content.encode("utf-8"))`, return `PaperCreateResult` from API JSON per content-endpoints.md create contract
- [ ] T042 [US1] Rewrite `DropboxService.update_paper()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.content_upload("files/paper/update", {"path": path, "import_format": {".tag": fmt}, "doc_update_policy": {".tag": policy}, "paper_revision": rev}, content.encode("utf-8"))`, return `PaperUpdateResult` from API JSON per content-endpoints.md update contract
- [ ] T043 [US1] Rewrite `DropboxService.resolve_shared_link_url()` as `async def` in src/dropbox_paper_cli/services/dropbox_service.py: call `self._client.rpc("sharing/get_shared_link_metadata", {"url": url})`, extract and return path from response per rpc-endpoints.md sharing contract
- [ ] T044 [US1] Remove `_IMPORT_FORMATS` and `_UPDATE_POLICIES` SDK enum mappings from src/dropbox_paper_cli/services/dropbox_service.py — replace with plain string-to-dict-tag mappings inline in create_paper/update_paper

### SharingService Rewrite

- [ ] T045 [US1] Rewrite `SharingService.__init__()` in src/dropbox_paper_cli/services/sharing_service.py to accept `client: DropboxHttpClient` instead of `dropbox.Dropbox`. Remove all `import dropbox` statements.
- [ ] T046 [US1] Rewrite `SharingService.get_sharing_info()` as `async def` in src/dropbox_paper_cli/services/sharing_service.py: call `self._client.rpc("sharing/get_folder_metadata", {"shared_folder_id": sid})`, call `_list_all_members()` for member list, return `SharingInfo.from_api(data, members)` per rpc-endpoints.md contract
- [ ] T047 [US1] Rewrite `SharingService._list_all_members()` as `async def` in src/dropbox_paper_cli/services/sharing_service.py: call `self._client.rpc("sharing/list_folder_members", {"shared_folder_id": sid, "limit": 200})`, handle cursor pagination via `sharing/list_folder_members/continue`, return `[MemberInfo.from_api(u) for u in users]`
- [ ] T048 [US1] Rewrite `SharingService.create_shared_link()` as `async def` in src/dropbox_paper_cli/services/sharing_service.py: call `self._client.rpc("sharing/create_shared_link_with_settings", {...})`, handle 409 `shared_link_already_exists` by extracting existing link per rpc-endpoints.md contract

### Service Tests

- [ ] T049 [P] [US1] Rewrite tests/unit/services/test_dropbox_service.py: replace all `dropbox.Dropbox` mock with `AsyncMock` of `DropboxHttpClient`, mock `.rpc()` / `.content_download()` / `.content_upload()` return values as JSON dicts matching API contracts, make all test functions `async def` with `@pytest.mark.asyncio`
- [ ] T050 [P] [US1] Rewrite tests/unit/services/test_sharing_service.py: replace `dropbox.Dropbox` mock with `AsyncMock` of `DropboxHttpClient`, mock `.rpc()` return values as JSON dicts matching sharing API contracts, make test functions `async def` with `@pytest.mark.asyncio`

### CLI Layer — asyncio.run() Bridge

- [ ] T051 [US1] Update `get_dropbox_service()` in src/dropbox_paper_cli/cli/common.py to return an async context manager factory yielding `DropboxService(DropboxHttpClient(...))` instead of sync `DropboxService(dropbox.Dropbox(...))`. Add `get_http_client()` helper per plan.md R-003 pattern.
- [ ] T052 [US1] Update src/dropbox_paper_cli/cli/files_browse.py: wrap each command's service calls in `asyncio.run()` using the pattern `asyncio.run(_cmd_async(...))` with `async def _cmd_async()` that uses `async with get_http_client() as client:` per R-003
- [ ] T053 [US1] Update src/dropbox_paper_cli/cli/files_content.py: wrap each command's service calls in `asyncio.run()` with async inner functions per R-003
- [ ] T054 [US1] Update src/dropbox_paper_cli/cli/files_organize.py: wrap each command's service calls in `asyncio.run()` with async inner functions per R-003
- [ ] T055 [US1] Update src/dropbox_paper_cli/cli/files.py: update `_resolve()` to be async, update import to use new service factory from common.py
- [ ] T056 [US1] Update src/dropbox_paper_cli/cli/sharing.py: wrap each command's service calls in `asyncio.run()` with async inner functions, instantiate `SharingService(client)` per R-003
- [ ] T057 [US1] Update src/dropbox_paper_cli/cli/cache.py: wrap sync command entry point in `asyncio.run()` per R-003

### CLI Tests

- [ ] T058 [P] [US1] Update tests/unit/cli/test_files.py: mock async service methods with `AsyncMock`, patch `asyncio.run` or use `CliRunner` with updated service factory
- [ ] T059 [P] [US1] Update tests/unit/cli/test_sharing.py: mock async service methods with `AsyncMock`, update assertions for new service factory pattern
- [ ] T060 [P] [US1] Update tests/unit/cli/test_common.py: test new `get_http_client()` factory, test async service creation pattern
- [ ] T061 [P] [US1] Update tests/unit/cli/test_cache.py: mock async sync entry point

**Checkpoint**: All existing CLI commands work identically via direct HTTP. User Story 1 is independently testable — run `uv run pytest tests/unit/ -v` and all tests pass with zero `import dropbox` in non-test code.

---

## Phase 4: User Story 2 — Authentication Flows Work Without the SDK (Priority: P1)

**Goal**: OAuth2 PKCE and Authorization Code flows work via direct HTTP requests, replacing `DropboxOAuth2FlowNoRedirect`. Token refresh is handled by `DropboxHttpClient` (built in Phase 2).

**Independent Test**: Run `paper auth login`, complete browser OAuth2 flow, verify token stored. Let token expire, run any command, verify auto-refresh occurs transparently. Run `paper auth logout`, verify tokens deleted.

### AuthService Rewrite

- [ ] T062 [US2] Implement `generate_pkce_pair()` function in src/dropbox_paper_cli/services/auth_service.py: generate 32-byte random `code_verifier` (base64url, no padding) and `code_challenge` (base64url SHA-256 of verifier) using only `secrets`, `hashlib`, `base64` per oauth2-endpoints.md PKCE implementation
- [ ] T063 [US2] Rewrite `AuthService.start_pkce_flow()` in src/dropbox_paper_cli/services/auth_service.py: build authorization URL `https://www.dropbox.com/oauth2/authorize` with query params (`client_id`, `response_type=code`, `code_challenge`, `code_challenge_method=S256`, `token_access_type=offline`), store `_code_verifier` for later exchange. Remove `DropboxOAuth2FlowNoRedirect` dependency.
- [ ] T064 [US2] Rewrite `AuthService.start_auth_code_flow()` in src/dropbox_paper_cli/services/auth_service.py: build authorization URL without PKCE params, using `client_secret` for token exchange per oauth2-endpoints.md auth code flow
- [ ] T065 [US2] Rewrite `AuthService.finish_flow()` as `async def` in src/dropbox_paper_cli/services/auth_service.py: POST to `https://api.dropboxapi.com/oauth2/token` with `grant_type=authorization_code`, `code`, `client_id`, and either `code_verifier` (PKCE) or `client_secret` (auth code) using httpx directly. Parse response to build `AuthToken` with `expires_at = time.time() + expires_in` per oauth2-endpoints.md token exchange contract.
- [ ] T066 [US2] Implement team namespace detection in `AuthService.finish_flow()` in src/dropbox_paper_cli/services/auth_service.py: after token exchange, call `users/get_current_account` via httpx to extract `root_namespace_id` and `home_namespace_id` from `root_info` when tag is `"team"`, persist into AuthToken per rpc-endpoints.md users/get_current_account contract
- [ ] T067 [US2] Remove all `import dropbox` and `from dropbox.oauth import DropboxOAuth2FlowNoRedirect` from src/dropbox_paper_cli/services/auth_service.py. Remove `dropbox.common.PathRoot` usage — replace with dict-based path root construction.
- [ ] T068 [US2] Update `AuthService.get_client()` in src/dropbox_paper_cli/services/auth_service.py (or replace with factory method) to return a configured `DropboxHttpClient` instance instead of `dropbox.Dropbox`. Pass stored token and app_key.

### Auth CLI Bridge

- [ ] T069 [US2] Update src/dropbox_paper_cli/cli/auth.py: wrap `login` command's `finish_flow()` call in `asyncio.run()` since it's now async. Keep `start_pkce_flow()` and URL display synchronous (URL building is sync). Update `logout` to remain sync (token file deletion is sync).

### Auth Tests

- [ ] T070 [P] [US2] Rewrite tests/unit/services/test_auth_service.py: remove all `dropbox.oauth` mocks, mock httpx POST calls to `oauth2/token` endpoint with JSON response fixtures per oauth2-endpoints.md, test PKCE flow (code_verifier/challenge generation, token exchange), test auth code flow, test team namespace detection, test `invalid_grant` error raising `AuthenticationError`, make async test methods
- [ ] T071 [P] [US2] Update tests/unit/cli/test_auth.py: mock async `finish_flow()`, test `asyncio.run()` bridge in login command, verify token persistence

**Checkpoint**: Authentication works end-to-end without Dropbox SDK. Both PKCE and auth-code flows function via direct HTTP. Token refresh is transparent.

---

## Phase 5: User Story 3 — Sync Operations Are Faster with Async Concurrency (Priority: P2)

**Goal**: Rewrite sync orchestrator from `ThreadPoolExecutor` + `Queue` to `asyncio.gather()` + `Semaphore(20)`. Single shared `AsyncClient` replaces per-thread SDK clones.

**Independent Test**: Run `paper sync` on a workspace with 100+ documents. Measure completion time. Verify incremental sync detects additions/modifications/deletions. Confirm concurrency is bounded by semaphore.

### SyncOrchestrator Rewrite

- [ ] T072 [US3] Rewrite `SyncOrchestrator.__init__()` in src/dropbox_paper_cli/services/sync_orchestrator.py: accept `conn: sqlite3.Connection` and `client: DropboxHttpClient` (instead of `dropbox.Dropbox`), remove `client_factory` parameter (no per-thread clones needed). Remove all `import dropbox` statements.
- [ ] T073 [US3] Rewrite `SyncOrchestrator.sync()` as `async def` in src/dropbox_paper_cli/services/sync_orchestrator.py: replace `ThreadPoolExecutor(max_workers=concurrency)` with `asyncio.Semaphore(concurrency)`, replace `Queue()` and `_SENTINEL` with direct `await`/return values, use `asyncio.gather(*tasks)` for concurrent folder listing per R-007 migration mapping table
- [ ] T074 [US3] Rewrite folder-level worker methods as `async def` in src/dropbox_paper_cli/services/sync_orchestrator.py: each folder listing acquires semaphore before calling `self._client.rpc("files/list_folder", ...)`, handles pagination via `files/list_folder/continue`, constructs `CachedMetadata` from API JSON, commits to SQLite in batches of 500 per R-007
- [ ] T075 [US3] Implement incremental sync detection as `async def` in src/dropbox_paper_cli/services/sync_orchestrator.py: use `list_folder` with cursor-based continuation for delta detection, handle cursor reset (409 with `reset` in error_summary) by falling back to full sync per rpc-endpoints.md cursor reset behavior
- [ ] T076 [US3] Implement graceful error handling in sync orchestrator in src/dropbox_paper_cli/services/sync_orchestrator.py: if a single folder fails, log error and continue syncing other folders (do not cancel all tasks). Collect errors for final SyncResult reporting.

### CacheService Update

- [ ] T077 [US3] Update `CacheService` sync delegation in src/dropbox_paper_cli/services/cache_service.py: change `sync()` method to `async def`, instantiate `SyncOrchestrator` with `DropboxHttpClient`, await orchestrator's async `sync()` method

### Sync Tests

- [ ] T078 [P] [US3] Rewrite tests/unit/services/test_cache_service.py: mock `DropboxHttpClient` instead of `dropbox.Dropbox`, make test methods `async def`, mock async sync orchestrator
- [ ] T079 [US3] Add new test cases in tests/unit/services/ for `SyncOrchestrator` async behavior: test concurrent folder listing with semaphore bound, test graceful error handling (one folder fails, others succeed), test cursor-based incremental sync, test cursor reset fallback to full sync. Use `AsyncMock` for `DropboxHttpClient.rpc()`.

**Checkpoint**: Sync operations use full async concurrency. `paper sync` works with `asyncio.gather()` + `Semaphore(20)`. Performance improvement measurable on large workspaces.

---

## Phase 6: User Story 4 — Robust Error Handling and Retry Behavior (Priority: P2)

**Goal**: Verify that the async retry logic (built in Phase 2) correctly handles all transient error scenarios. This story is largely satisfied by Phases 2 and 3, but needs integration-level validation.

**Independent Test**: Simulate network errors (connection timeouts, 429 rate limits, 500 server errors) and verify retries occur with correct backoff. Verify `Retry-After` header is respected. Verify token refresh on 401 is transparent.

### Error Handling Refinement

- [ ] T080 [US4] Add `NetworkError` mapping for `httpx.ConnectError` and `httpx.ReadTimeout` in src/dropbox_paper_cli/lib/http_client.py `_request()` method: catch httpx transport errors and wrap as `NetworkError` with clear user-facing messages after retry exhaustion
- [ ] T081 [US4] Ensure `Retry-After` header from 429 responses overrides exponential backoff delay in src/dropbox_paper_cli/lib/retry.py: parse header as integer seconds, use as sleep duration instead of calculated backoff per R-005 decision table

### Error Handling Tests

- [ ] T082 [P] [US4] Add integration-level error scenario tests in tests/unit/lib/test_http_client.py: test 429 → retry with Retry-After delay, test 500 → retry with exponential backoff (3 attempts), test connection timeout → retry, test all retries exhausted → clear error message, test 401 → token refresh → retry succeeds
- [ ] T083 [P] [US4] Add test for concurrent 401 handling in tests/unit/lib/test_http_client.py: simulate 20 concurrent requests all receiving 401, verify only one token refresh occurs (asyncio.Lock coordination), verify all requests succeed after refresh

**Checkpoint**: All transient error scenarios are handled with correct retry behavior. Rate limits respected. Token refresh transparent and coordinated.

---

## Phase 7: User Story 5 — Dropbox SDK Dependency Is Fully Removed (Priority: P3)

**Goal**: Verify complete removal of `dropbox` package. No `import dropbox` anywhere. All tests pass with only `httpx`.

### Cleanup

- [ ] T084 [US5] Search entire codebase for any remaining `import dropbox` or `from dropbox` statements and remove them — verify zero results with `grep -r "import dropbox\|from dropbox" src/`
- [ ] T085 [US5] Remove any remaining SDK-specific error handling patterns (e.g., `dropbox.exceptions.ApiError` catches) across all files in src/dropbox_paper_cli/
- [ ] T086 [US5] Update tests/conftest.py: remove any SDK-related shared fixtures, add shared httpx mock fixtures (e.g., `mock_http_client` returning `AsyncMock` of `DropboxHttpClient` with sensible defaults)
- [ ] T087 [US5] Verify pyproject.toml has no `dropbox` in dependencies and `httpx>=0.27.0` is present, `pytest-httpx>=0.30.0` in dev dependencies
- [ ] T088 [US5] Run full test suite `uv run pytest tests/ -v` to confirm all tests pass with updated mocks and no dropbox dependency
- [ ] T089 [US5] Run `uv run ruff check src/ tests/` and `uv run ruff format --check src/ tests/` to verify code quality after migration

### Integration Smoke Test

- [ ] T090 [US5] Update tests/integration/test_smoke.py: replace any SDK-based smoke test setup with async service calls via `DropboxHttpClient`, update assertions for API JSON responses

**Checkpoint**: `dropbox` package is completely absent. `import dropbox` returns zero grep results. Full test suite passes. Linting clean.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Observability, documentation, final validation

- [ ] T091 [P] Implement `--verbose` flag wiring in src/dropbox_paper_cli/app.py: when `--verbose` is passed, set root logger to DEBUG level so `dropbox_paper_cli.lib.http_client` DEBUG logs become visible per R-010
- [ ] T092 [P] Implement `PAPER_LOG_LEVEL` environment variable support in src/dropbox_paper_cli/app.py: read env var at startup, configure logging level accordingly per FR-021
- [ ] T093 [P] Update src/dropbox_paper_cli/tui/search.py if it references any SDK types or sync service calls — verify it works with async service layer (TUI is already async via Textual per plan.md)
- [ ] T094 Run quickstart.md validation: execute all commands from specs/002-httpx-api-migration/quickstart.md setup and test sections to verify documented workflows work
- [ ] T095 Run full test suite with verbose logging: `PAPER_LOG_LEVEL=DEBUG uv run pytest tests/unit/ -v` and verify DEBUG HTTP logs appear, no test regressions
- [ ] T096 Verify type checking passes: `uv run ty check src/` — resolve any type errors introduced by async migration

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 — core SDK replacement
- **User Story 2 (Phase 4)**: Depends on Phase 2 — auth rewrite (independent of US1)
- **User Story 3 (Phase 5)**: Depends on Phase 2 + Phase 3 (sync orchestrator needs rewritten DropboxService)
- **User Story 4 (Phase 6)**: Depends on Phase 2 — error handling validation (can run in parallel with US1/US2)
- **User Story 5 (Phase 7)**: Depends on Phases 3, 4, 5 — final cleanup requires all rewrites complete
- **Polish (Phase 8)**: Depends on all user stories

### User Story Dependencies

```
Phase 1 (Setup)
    │
    ▼
Phase 2 (Foundational: HTTP client + async retry)
    │
    ├──────────────────┬──────────────────┐
    ▼                  ▼                  ▼
Phase 3 (US1: P1)  Phase 4 (US2: P1)  Phase 6 (US4: P2)
CLI commands        Auth flows          Error handling
    │                  │                  │
    ├──────────────────┘                  │
    ▼                                     │
Phase 5 (US3: P2)                         │
Async sync                                │
    │                                     │
    ├─────────────────────────────────────┘
    ▼
Phase 7 (US5: P3)
SDK removal
    │
    ▼
Phase 8 (Polish)
```

### Within Each User Story

- Models before services (services depend on `from_api()`)
- Services before CLI layer (CLI wraps service calls)
- Tests can be written in parallel with implementation (marked [P])
- Each phase checkpoint validates independently

### Parallel Opportunities

- **Phase 2**: T019–T025 (all foundational tests) can run in parallel
- **Phase 3**: T026–T030 (all model tasks) can run in parallel; T031–T032 (model tests) in parallel; T036–T039 (move/copy/delete/mkdir) in parallel; T049–T050 (service tests) in parallel; T058–T061 (CLI tests) in parallel
- **Phase 4**: T070–T071 (auth tests) can run in parallel
- **Phase 3 & Phase 4**: Can be worked on in parallel by different developers (independent services)
- **Phase 6**: T082–T083 (error tests) can run in parallel with US1/US2 implementation

---

## Parallel Example: User Story 1 (Phase 3)

```bash
# Launch all model rewrites in parallel (different files):
Task T026: "Add DropboxItem.from_api() in src/dropbox_paper_cli/models/items.py"
Task T029: "Add MemberInfo.from_api() in src/dropbox_paper_cli/models/sharing.py"
Task T030: "Add SharingInfo.from_api() in src/dropbox_paper_cli/models/sharing.py"

# Launch model tests in parallel (different files):
Task T031: "Rewrite tests/unit/models/test_items.py"
Task T032: "Rewrite tests/unit/models/test_sharing.py"

# After models complete, launch independent service methods in parallel:
Task T036: "Rewrite DropboxService.move() in services/dropbox_service.py"
Task T037: "Rewrite DropboxService.copy() in services/dropbox_service.py"
Task T038: "Rewrite DropboxService.delete() in services/dropbox_service.py"
Task T039: "Rewrite DropboxService.create_folder() in services/dropbox_service.py"

# Launch service tests in parallel (different files):
Task T049: "Rewrite tests/unit/services/test_dropbox_service.py"
Task T050: "Rewrite tests/unit/services/test_sharing_service.py"

# Launch CLI tests in parallel (different files):
Task T058: "Update tests/unit/cli/test_files.py"
Task T059: "Update tests/unit/cli/test_sharing.py"
Task T060: "Update tests/unit/cli/test_common.py"
Task T061: "Update tests/unit/cli/test_cache.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only)

1. Complete Phase 1: Setup (dependency swap)
2. Complete Phase 2: Foundational (HTTP client + async retry) — CRITICAL GATE
3. Complete Phase 3: User Story 1 (all CLI commands work via HTTP)
4. Complete Phase 4: User Story 2 (auth flows work via HTTP)
5. **STOP and VALIDATE**: All commands work, auth works, all unit tests pass
6. This is a deployable MVP — the SDK is functionally replaced

### Incremental Delivery

1. Setup + Foundational → HTTP infrastructure ready
2. Add US1 (CLI commands) → Test independently → Core migration done (MVP!)
3. Add US2 (Auth flows) → Test independently → Full user-facing migration
4. Add US3 (Async sync) → Test independently → Performance improvement delivered
5. Add US4 (Error handling validation) → Test independently → Reliability confirmed
6. Add US5 (SDK removal) → Test independently → Clean dependency tree
7. Polish → Documentation, logging, final validation

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (Phases 1–2)
2. Once Foundational is done:
   - Developer A: User Story 1 (CLI commands — largest surface area)
   - Developer B: User Story 2 (Auth flows — independent service)
   - Developer C: User Story 4 (Error handling tests — parallel safe)
3. After US1 completes → Developer A starts US3 (Sync orchestrator needs rewritten DropboxService)
4. After US1+US2+US3 → Anyone does US5 (cleanup pass)
5. Polish phase after all stories complete

---

## Notes

- All service methods become `async def` — this is a one-way migration (R-003)
- `asyncio.run()` boundary is at each CLI command entry point only (not nested)
- SQLite calls remain synchronous within async code (acceptable for CLI tool per R-007)
- Token file format is unchanged — existing users don't need to re-authenticate (FR-015)
- The Dropbox SDK JSON field names match the API JSON keys exactly (auto-generated SDK per R-011)
- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps each task to its user story for traceability
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
