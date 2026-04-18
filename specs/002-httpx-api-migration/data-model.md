# Data Model: Replace Dropbox SDK with Direct HTTP API + httpx

**Feature**: 002-httpx-api-migration
**Date**: 2025-07-15

## Entity Overview

This migration does NOT add new persistent entities. It modifies how existing entities are constructed (from API JSON instead of SDK objects) and introduces runtime-only entities for the HTTP client layer.

### Entity Relationship Diagram

```
┌─────────────────────┐          ┌──────────────────────┐
│   DropboxHttpClient  │◄────────│    AuthService        │
│  (runtime, new)      │         │  (rewritten)          │
│                      │         │                       │
│  - _client: AsyncCl. │         │  - _http_client       │
│  - _token: AuthToken │         │  - _token: AuthToken  │
│  - _refresh_lock     │         │  - _code_verifier     │
│  - _app_key          │         │                       │
└──────────┬───────────┘         └───────────────────────┘
           │ used by
     ┌─────┴──────────────────┐
     │                        │
┌────▼──────────┐   ┌────────▼────────┐   ┌─────────────────┐
│DropboxService │   │ SharingService  │   │SyncOrchestrator │
│ (rewritten)   │   │ (rewritten)     │   │ (rewritten)     │
│               │   │                 │   │                 │
│ → DropboxItem │   │ → SharingInfo   │   │ → CachedMetadata│
│ → PaperCreate │   │ → MemberInfo    │   │ → SyncResult    │
│ → PaperUpdate │   │                 │   │                 │
└───────────────┘   └─────────────────┘   └─────────────────┘

Existing (unchanged):
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  AuthToken   │  │ CachedMetadata│  │  SyncState   │
│  (models/)   │  │  (models/)   │  │  (models/)   │
│  persisted   │  │  SQLite rows │  │  SQLite rows │
└──────────────┘  └──────────────┘  └──────────────┘
```

---

## New Entity: DropboxHttpClient

**Module**: `src/dropbox_paper_cli/lib/http_client.py`
**Lifetime**: Runtime only (created per CLI command invocation, not persisted)
**Role**: Central async HTTP client encapsulating all Dropbox API communication

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `_client` | `httpx.AsyncClient` | Shared HTTP client with connection pooling |
| `_token` | `AuthToken` | Current OAuth2 credentials (mutable on refresh) |
| `_app_key` | `str` | Dropbox app key for token refresh |
| `_token_persister` | `Callable[[AuthToken], None] \| None` | Optional callback to persist refreshed tokens to disk (e.g., `auth_service.save_token`) |
| `_refresh_lock` | `asyncio.Lock` | Coordinates concurrent token refresh |
| `_logger` | `logging.Logger` | DEBUG-level HTTP request logging |

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(token: AuthToken, app_key: str, *, token_persister: Callable[[AuthToken], None] \| None = None)` | Create client with auth state and optional token persistence callback |
| `__aenter__` | `async def` | Initialize httpx.AsyncClient |
| `__aexit__` | `async def` | Close httpx.AsyncClient |
| `rpc` | `async def rpc(endpoint: str, params: dict \| None = None, *, timeout: Timeout = METADATA_TIMEOUT) -> dict` | RPC endpoint call (JSON in/out) |
| `content_download` | `async def content_download(endpoint: str, params: dict, *, timeout: Timeout = CONTENT_TIMEOUT) -> tuple[bytes, dict]` | Content-download (binary body + metadata header) |
| `content_upload` | `async def content_upload(endpoint: str, params: dict, data: bytes, *, timeout: Timeout = CONTENT_TIMEOUT) -> dict` | Content-upload (binary body, JSON response) |
| `_request` | `async def _request(method: str, url: str, **kwargs) -> httpx.Response` | Low-level request with auth, retry on 401 |
| `_handle_401` | `async def _handle_401() -> None` | Double-check lock token refresh |
| `_refresh_token` | `async def _refresh_token() -> AuthToken` | POST to oauth2/token |
| `_raise_for_api_error` | `def _raise_for_api_error(response: httpx.Response) -> Never` | Parse Dropbox error JSON → AppError |
| `_auth_headers` | `def _auth_headers() -> dict[str, str]` | Bearer token + optional path root |

### Validation Rules

- `_token` must have non-empty `access_token` and `refresh_token`
- `_app_key` must be non-empty
- Client must be used within `async with` context manager (enforced by httpx)
- Token refresh must succeed or raise `AuthenticationError` (refresh token revoked)

### State Transitions

```
┌──────────┐     __aenter__()      ┌──────────┐
│  Created  │ ──────────────────► │  Active   │
│ (no conn) │                     │ (pooled)  │
└──────────┘                     └─────┬─────┘
                                       │
                              ┌────────┴────────┐
                              │                 │
                         401 received      Normal request
                              │                 │
                     ┌────────▼────────┐        │
                     │  Refreshing     │        │
                     │ (lock held)     │        │
                     └────────┬────────┘        │
                              │                 │
                         Token updated          │
                              │                 │
                              ▼                 │
                         ┌────────────┐         │
                         │  Active    │◄────────┘
                         │ (new token)│
                         └─────┬──────┘
                               │
                          __aexit__()
                               │
                        ┌──────▼──────┐
                        │   Closed    │
                        │ (conn freed)│
                        └─────────────┘
```

---

## Modified Entity: DropboxItem

**Module**: `src/dropbox_paper_cli/models/items.py`
**Change**: Add `from_api()` classmethod, remove `from_sdk()` classmethod

### Current `from_sdk()` (to be removed)

```python
@classmethod
def from_sdk(cls, metadata) -> "DropboxItem":
    # Accepts dropbox.files.FileMetadata or FolderMetadata
    is_folder = isinstance(metadata, dropbox.files.FolderMetadata)
    # ... maps SDK attributes to dataclass fields
```

### New `from_api()` (to be added)

```python
@classmethod
def from_api(cls, data: dict) -> "DropboxItem":
    """Construct from Dropbox API JSON response dict."""
    tag = data.get(".tag", "file")
    return cls(
        id=data.get("id", ""),
        name=data.get("name", ""),
        path_display=data.get("path_display", ""),
        path_lower=data.get("path_lower", ""),
        type="folder" if tag == "folder" else "file",
        size=data.get("size"),
        server_modified=datetime.fromisoformat(data["server_modified"]) if data.get("server_modified") else None,
        rev=data.get("rev"),
        content_hash=data.get("content_hash"),
    )
```

### Field Mapping (SDK attr → API JSON key)

| Dataclass Field | SDK Attribute | API JSON Key | Notes |
|----------------|--------------|-------------|-------|
| `id` | `metadata.id` | `"id"` | Same |
| `name` | `metadata.name` | `"name"` | Same |
| `path_display` | `metadata.path_display` | `"path_display"` | Same |
| `path_lower` | `metadata.path_lower` | `"path_lower"` | Same |
| `type` | `isinstance(m, FolderMetadata)` | `".tag"` value | `"folder"` or `"file"` |
| `size` | `metadata.size` | `"size"` | Files only; None for folders |
| `server_modified` | `metadata.server_modified` | `"server_modified"` | Files only; ISO 8601 string → parse to `datetime` via `datetime.fromisoformat()` |
| `rev` | `metadata.rev` | `"rev"` | Files only |
| `content_hash` | `metadata.content_hash` | `"content_hash"` | Files only |

---

## Modified Entity: PaperCreateResult

**Module**: `src/dropbox_paper_cli/models/items.py`
**Change**: Constructed from API JSON instead of SDK result object

### API JSON Response

```json
{
    "url": "https://www.dropbox.com/scl/fi/...",
    "result_path": "/path/to/doc.paper",
    "file_id": "id:...",
    "paper_revision": 1
}
```

Maps directly to existing dataclass fields (same names).

---

## Modified Entity: PaperUpdateResult

**Module**: `src/dropbox_paper_cli/models/items.py`
**Change**: Constructed from API JSON instead of SDK result object

### API JSON Response

```json
{
    "paper_revision": 2
}
```

Maps directly to existing dataclass field.

---

## Modified Entity: MemberInfo

**Module**: `src/dropbox_paper_cli/models/sharing.py`
**Change**: Add `from_api()`, remove `from_sdk()`

### API JSON Structure (from list_folder_members)

```json
{
    "users": [
        {
            "access_type": { ".tag": "editor" },
            "user": {
                "account_id": "dbid:...",
                "display_name": "Jane Doe",
                "email": "jane@example.com"
            },
            "is_inherited": false
        }
    ],
    "cursor": "..."
}
```

### Field Mapping

| Dataclass Field | SDK Access Path | API JSON Path |
|----------------|----------------|--------------|
| `account_id` | `m.user.account_id` | `entry["user"]["account_id"]` |
| `display_name` | `m.user.display_name` | `entry["user"]["display_name"]` |
| `email` | `m.user.email` | `entry["user"]["email"]` |
| `access_type` | `m.access_type._tag` | `entry["access_type"][".tag"]` |

---

## Modified Entity: SharingInfo

**Module**: `src/dropbox_paper_cli/models/sharing.py`
**Change**: Add `from_api()`, remove `from_sdk()`

### API JSON Structure (from get_folder_metadata)

```json
{
    "shared_folder_id": "...",
    "name": "Shared Folder",
    "path_lower": "/shared folder",
    "access_type": { ".tag": "owner" }
}
```

### Field Mapping

| Dataclass Field | SDK Access Path | API JSON Path |
|----------------|----------------|--------------|
| `shared_folder_id` | `m.shared_folder_id` | `data["shared_folder_id"]` |
| `name` | `m.name` | `data["name"]` |
| `path_display` | `m.path_display` or fallback | `data.get("path_display", "")` |
| `members` | Populated separately | Populated separately via list_folder_members |

---

## Unchanged Entities

### AuthToken (`models/auth.py`)
- **No changes needed**: Already a pure dataclass with `to_dict()`/`from_dict()`. No SDK dependencies. Token file format (JSON with 0600 permissions) remains identical.

### CachedMetadata (`models/cache.py`)
- **No changes needed**: Constructed from `SyncOrchestrator` internal logic, not directly from SDK objects. The orchestrator will construct these from API JSON instead, but the model itself is unchanged.

### SyncState, SyncResult (`models/sync.py`)
- **No changes needed**: Pure state/result tracking dataclasses. No SDK dependencies.

### ExitCode, AppError hierarchy (`lib/errors.py`)
- **No changes needed**: These are the TARGET of error mapping, not the source. The HTTP client maps API errors TO these types.

---

## Summary of Changes

| Entity | File | Change Type | SDK Dependency Removed |
|--------|------|-------------|----------------------|
| `DropboxHttpClient` | lib/http_client.py | **NEW** | N/A (new) |
| `DropboxItem` | models/items.py | **MODIFIED** | `dropbox.files.FileMetadata`, `FolderMetadata` |
| `PaperCreateResult` | models/items.py | **MODIFIED** (minor) | SDK result object |
| `PaperUpdateResult` | models/items.py | **MODIFIED** (minor) | SDK result object |
| `MemberInfo` | models/sharing.py | **MODIFIED** | `dropbox.UserMembershipInfo` |
| `SharingInfo` | models/sharing.py | **MODIFIED** | `dropbox.SharedFolderMetadata` |
| `AuthToken` | models/auth.py | UNCHANGED | None (already pure) |
| `CachedMetadata` | models/cache.py | UNCHANGED | None (already pure) |
| `SyncState` | models/sync.py | UNCHANGED | None (already pure) |
| `SyncResult` | models/sync.py | UNCHANGED | None (already pure) |
