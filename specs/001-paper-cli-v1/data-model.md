# Data Model: Dropbox Paper CLI v1.0

**Date**: 2025-07-18
**Feature**: 001-paper-cli-v1

## Domain Entities

### AuthToken

Represents the user's persisted OAuth2 credentials.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `access_token` | string | required | Short-lived access token from Dropbox |
| `refresh_token` | string | required | Long-lived refresh token (offline access) |
| `expires_at` | float (epoch) | required | Unix timestamp when access_token expires |
| `account_id` | string | required | Dropbox account identifier (e.g., `dbid:xxx`) |
| `uid` | string | optional | Dropbox user ID |
| `token_type` | string | default `"bearer"` | Token type |

**Storage**: JSON file at `~/.dropbox-paper-cli/tokens.json` with file permissions `0600`.

**State Transitions**:
- `absent` → `active`: After successful OAuth2 flow completion
- `active` → `expired`: When `time.time() >= expires_at`
- `expired` → `active`: After automatic refresh using `refresh_token`
- `active` → `revoked`: When user runs `auth logout` or token is invalidated server-side
- `revoked` → `absent`: Token file is deleted

**Validation Rules**:
- `access_token` and `refresh_token` must be non-empty strings
- `expires_at` must be a positive float
- `account_id` must be a non-empty string

---

### DropboxItem

Represents a file or folder in the remote Dropbox namespace. This is the SDK response model.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | string | required, unique | Dropbox item ID (e.g., `id:xxx`) |
| `name` | string | required | Display name |
| `path_display` | string | required | Human-readable path |
| `path_lower` | string | required | Lowercased path for comparisons |
| `type` | enum | `"file"` \| `"folder"` | Determined by SDK metadata class |
| `size` | int \| None | files only | Size in bytes; `None` for folders |
| `server_modified` | datetime \| None | files only | Last modified on server |
| `rev` | string \| None | files only | Revision hash for content changes |
| `content_hash` | string \| None | files only | Hash of file content |
| `is_paper` | bool | derived | `True` if `name.endswith('.paper')` |

**Mapping from SDK**:
- `dropbox.files.FileMetadata` → `DropboxItem(type="file")`
- `dropbox.files.FolderMetadata` → `DropboxItem(type="folder")`
- `dropbox.files.DeletedMetadata` → signals deletion during sync

---

### PaperDocument

A specialized view of a `DropboxItem` that adds content retrieval. Not a separate stored entity — it's a `DropboxItem` where `is_paper == True` plus the result of `files_export()`.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| *All fields from DropboxItem* | | | |
| `content_markdown` | string | retrieved on demand | Markdown export of Paper document |

**Retrieval**: Via `dbx.files_export(path)` — returns markdown content as a streaming response.

---

### SharingInfo

Represents sharing metadata for a shared folder.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `shared_folder_id` | string | required | Shared folder identifier |
| `name` | string | required | Folder name |
| `path_display` | string | optional | Path if mounted |
| `policy` | object | required | Sharing policy details |
| `members` | list[MemberInfo] | required | List of folder members |

### MemberInfo

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `account_id` | string | required | Dropbox account ID |
| `display_name` | string | required | Human-readable name |
| `email` | string | required | Email address |
| `access_type` | enum | `"owner"` \| `"editor"` \| `"viewer"` \| `"viewer_no_comment"` | Permission level |

---

### CachedMetadata

Represents a locally-stored metadata entry in the SQLite cache. Mirrors `DropboxItem` with sync-tracking fields.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | TEXT | PRIMARY KEY | Dropbox item ID |
| `name` | TEXT | NOT NULL | Display name |
| `path_display` | TEXT | UNIQUE, NOT NULL | Human-readable path |
| `path_lower` | TEXT | NOT NULL | Lowercased path for comparisons |
| `is_dir` | INTEGER | NOT NULL, 0 or 1 | 1 for folder, 0 for file |
| `parent_path` | TEXT | nullable | Parent folder's `path_lower` |
| `size_bytes` | INTEGER | nullable | File size; NULL for folders |
| `server_modified` | TEXT | nullable | ISO 8601; NULL for folders |
| `rev` | TEXT | nullable | Dropbox revision; NULL for folders |
| `content_hash` | TEXT | nullable | File content hash; NULL for folders |
| `synced_at` | TEXT | NOT NULL | ISO 8601 timestamp of last sync |

### SyncState

Tracks the cursor position for incremental sync.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `key` | TEXT | PRIMARY KEY | Always `"default"` for v1 |
| `cursor` | TEXT | nullable | Dropbox folder cursor for `files_list_folder_continue` |
| `last_sync_at` | TEXT | nullable | ISO 8601 timestamp of last successful sync |
| `total_items` | INTEGER | default 0 | Number of items in cache after last sync |

---

## SQLite Schema

```sql
-- Core metadata table
CREATE TABLE IF NOT EXISTS metadata (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    path_display    TEXT UNIQUE NOT NULL,
    path_lower      TEXT NOT NULL,
    is_dir          INTEGER NOT NULL DEFAULT 0,
    parent_path     TEXT,
    size_bytes      INTEGER,
    server_modified TEXT,
    rev             TEXT,
    content_hash    TEXT,
    synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_metadata_parent_path ON metadata(parent_path);
CREATE INDEX IF NOT EXISTS idx_metadata_is_dir ON metadata(is_dir);
CREATE INDEX IF NOT EXISTS idx_metadata_name ON metadata(name);

-- FTS5 virtual table for keyword search
CREATE VIRTUAL TABLE IF NOT EXISTS metadata_fts USING fts5(
    name,
    path_display,
    content=metadata,
    content_rowid=rowid,
    tokenize='unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS metadata_fts_insert AFTER INSERT ON metadata BEGIN
    INSERT INTO metadata_fts(rowid, name, path_display)
    VALUES (new.rowid, new.name, new.path_display);
END;

CREATE TRIGGER IF NOT EXISTS metadata_fts_delete AFTER DELETE ON metadata BEGIN
    INSERT INTO metadata_fts(metadata_fts, rowid, name, path_display)
    VALUES ('delete', old.rowid, old.name, old.path_display);
END;

CREATE TRIGGER IF NOT EXISTS metadata_fts_update AFTER UPDATE ON metadata BEGIN
    INSERT INTO metadata_fts(metadata_fts, rowid, name, path_display)
    VALUES ('delete', old.rowid, old.name, old.path_display);
    INSERT INTO metadata_fts(rowid, name, path_display)
    VALUES (new.rowid, new.name, new.path_display);
END;

-- Sync state tracking
CREATE TABLE IF NOT EXISTS sync_state (
    key             TEXT PRIMARY KEY,
    cursor          TEXT,
    last_sync_at    TEXT,
    total_items     INTEGER DEFAULT 0
);

-- Schema version for future migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

## Entity Relationships

```
AuthToken (filesystem)
  └── used by → Dropbox SDK Client

DropboxItem (remote API)
  ├── synced to → CachedMetadata (SQLite)
  ├── specialized as → PaperDocument (when is_paper=True)
  └── may have → SharingInfo (for shared folders)

CachedMetadata (SQLite)
  ├── parent_path → CachedMetadata (self-referencing tree)
  ├── indexed by → metadata_fts (FTS5 virtual table)
  └── tracked by → SyncState (cursor position)

SharingInfo (remote API)
  └── contains → MemberInfo[] (folder members)
```
