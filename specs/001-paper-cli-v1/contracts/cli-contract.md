# CLI Contract: Dropbox Paper CLI v1.0

**Date**: 2025-07-18
**Feature**: 001-paper-cli-v1

This document defines the CLI interface contract — the commands, arguments, flags, output formats, and exit codes that constitute the public API of `paper`.

## Global Options

All commands inherit these options from the top-level callback:

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--json` | | bool | `false` | Output structured JSON to stdout |
| `--verbose` | `-v` | bool | `false` | Emit diagnostic info to stderr |
| `--help` | | bool | | Show help text |
| `--version` | | bool | | Show version and exit |

## Exit Codes

| Code | Meaning | When |
|------|---------|------|
| 0 | Success | Command completed normally |
| 1 | General error | Unclassified failure |
| 2 | Authentication error | Token missing, expired+unrefreshable, or revoked |
| 3 | Not found | Requested file/folder/path does not exist |
| 4 | Validation error | Invalid arguments, unparseable URL, conflicting flags |
| 5 | Network/API error | Connection failure, rate limit exhausted, server error after retries |
| 6 | Permission error | Insufficient permissions for the requested operation |

## Error Output Contract

All errors are written to **stderr**. In `--json` mode, errors are also formatted as JSON on stderr:

```json
{
  "error": "Human-readable error message",
  "code": "MACHINE_READABLE_CODE"
}
```

Machine-readable codes: `AUTH_REQUIRED`, `AUTH_EXPIRED`, `TOKEN_REVOKED`, `NOT_FOUND`, `INVALID_INPUT`, `URL_PARSE_ERROR`, `CONFLICT`, `PERMISSION_DENIED`, `NETWORK_ERROR`, `RATE_LIMITED`, `API_ERROR`, `CACHE_NOT_FOUND`.

---

## Command Group: `auth`

### `paper auth login`

Initiate OAuth2 authentication flow.

```
paper auth login [--flow <pkce|code>]
```

| Argument/Flag | Type | Default | Description |
|---------------|------|---------|-------------|
| `--flow` | enum | `pkce` | OAuth2 flow type: `pkce` (no server) or `code` (with redirect) |

**Stdout (default)**:
```
Opening browser for Dropbox authorization...
Authorization URL: https://www.dropbox.com/oauth2/authorize?...

Paste the authorization code: <user input>

✓ Authenticated as Jane Doe (jane@example.com)
  Account ID: dbid:AADxxxxxxx
  Token stored at: ~/.dropbox-paper-cli/tokens.json
```

**Stdout (`--json`)**:
```json
{
  "status": "authenticated",
  "account_id": "dbid:AADxxxxxxx",
  "display_name": "Jane Doe",
  "email": "jane@example.com",
  "token_path": "~/.dropbox-paper-cli/tokens.json"
}
```

### `paper auth logout`

Clear stored credentials.

```
paper auth logout
```

**Stdout (default)**: `✓ Credentials removed.`

**Stdout (`--json`)**:
```json
{ "status": "logged_out" }
```

### `paper auth status`

Check current authentication state.

```
paper auth status
```

**Stdout (default)**:
```
Authenticated as Jane Doe (jane@example.com)
Account ID: dbid:AADxxxxxxx
Token expires: 2025-07-18T15:30:00Z
```

**Stdout (`--json`)**:
```json
{
  "authenticated": true,
  "account_id": "dbid:AADxxxxxxx",
  "display_name": "Jane Doe",
  "email": "jane@example.com",
  "expires_at": "2025-07-18T15:30:00Z"
}
```

---

## Command Group: `files`

### `paper files list`

List files and folders at a Dropbox path.

```
paper files list [PATH] [--recursive]
```

| Argument/Flag | Type | Default | Description |
|---------------|------|---------|-------------|
| `PATH` | string | `""` (root) | Dropbox path to list |
| `--recursive` | bool | `false` | List all items recursively |

**Stdout (default)**:
```
📁 Project Notes/        2025-07-15
📁 Archive/              2025-06-01
📄 Meeting Notes.paper   2025-07-18  12.4 KB
📄 TODO.paper            2025-07-17   3.1 KB
```

**Stdout (`--json`)**:
```json
{
  "path": "",
  "items": [
    {
      "id": "id:abc123",
      "name": "Project Notes",
      "path": "/Project Notes",
      "type": "folder",
      "modified": "2025-07-15T10:30:00Z"
    },
    {
      "id": "id:def456",
      "name": "Meeting Notes.paper",
      "path": "/Meeting Notes.paper",
      "type": "file",
      "modified": "2025-07-18T09:00:00Z",
      "size": 12700
    }
  ]
}
```

### `paper files metadata`

Get detailed metadata for a specific file or folder.

```
paper files metadata <TARGET>
```

| Argument | Type | Description |
|----------|------|-------------|
| `TARGET` | string | File ID, path, or Dropbox Paper URL |

**Stdout (default)**:
```
Name:     Meeting Notes.paper
Type:     file
Path:     /Project Notes/Meeting Notes.paper
ID:       id:abc123
Size:     12,700 bytes
Modified: 2025-07-18T09:00:00Z
Rev:      015f2b3c4d5e6
```

**Stdout (`--json`)**:
```json
{
  "id": "id:abc123",
  "name": "Meeting Notes.paper",
  "path": "/Project Notes/Meeting Notes.paper",
  "type": "file",
  "size": 12700,
  "modified": "2025-07-18T09:00:00Z",
  "rev": "015f2b3c4d5e6",
  "content_hash": "a1b2c3..."
}
```

### `paper files read`

Read and output Paper document content as Markdown.

```
paper files read <TARGET>
```

| Argument | Type | Description |
|----------|------|-------------|
| `TARGET` | string | File ID, path, or Dropbox Paper URL |

**Stdout (default)**: Raw Markdown content of the document.

**Stdout (`--json`)**:
```json
{
  "id": "id:abc123",
  "name": "Meeting Notes.paper",
  "path": "/Project Notes/Meeting Notes.paper",
  "content": "# Meeting Notes\n\n## 2025-07-18\n\n- Discussed project timeline...",
  "format": "markdown"
}
```

### `paper files move`

Move a file or folder to a new location.

```
paper files move <SOURCE> <DESTINATION>
```

| Argument | Type | Description |
|----------|------|-------------|
| `SOURCE` | string | Source file ID, path, or URL |
| `DESTINATION` | string | Destination path |

**Stdout (default)**:
```
✓ Moved "Meeting Notes.paper"
  From: /old/path/Meeting Notes.paper
  To:   /new/path/Meeting Notes.paper
```

**Stdout (`--json`)**:
```json
{
  "status": "moved",
  "name": "Meeting Notes.paper",
  "from": "/old/path/Meeting Notes.paper",
  "to": "/new/path/Meeting Notes.paper",
  "id": "id:abc123"
}
```

### `paper files copy`

Copy a file or folder to a new location.

```
paper files copy <SOURCE> <DESTINATION>
```

| Argument | Type | Description |
|----------|------|-------------|
| `SOURCE` | string | Source file ID, path, or URL |
| `DESTINATION` | string | Destination path |

**Stdout (default)**:
```
✓ Copied "Meeting Notes.paper"
  To: /copies/Meeting Notes.paper
  New ID: id:xyz789
```

**Stdout (`--json`)**:
```json
{
  "status": "copied",
  "name": "Meeting Notes.paper",
  "from": "/original/Meeting Notes.paper",
  "to": "/copies/Meeting Notes.paper",
  "new_id": "id:xyz789"
}
```

### `paper files delete`

Delete a file or folder.

```
paper files delete <TARGET>
```

| Argument | Type | Description |
|----------|------|-------------|
| `TARGET` | string | File ID, path, or URL |

**Stdout (default)**: `✓ Deleted "Meeting Notes.paper"`

**Stdout (`--json`)**:
```json
{
  "status": "deleted",
  "name": "Meeting Notes.paper",
  "path": "/old/path/Meeting Notes.paper",
  "id": "id:abc123"
}
```

### `paper files create-folder`

Create a new folder.

```
paper files create-folder <PATH>
```

| Argument | Type | Description |
|----------|------|-------------|
| `PATH` | string | Path for the new folder |

**Stdout (default)**:
```
✓ Created folder "New Folder"
  Path: /path/to/New Folder
  ID:   id:folder789
```

**Stdout (`--json`)**:
```json
{
  "status": "created",
  "name": "New Folder",
  "path": "/path/to/New Folder",
  "id": "id:folder789",
  "type": "folder"
}
```

### `paper files link`

Get or create a sharing link for a file.

```
paper files link <TARGET>
```

| Argument | Type | Description |
|----------|------|-------------|
| `TARGET` | string | File ID, path, or URL |

**Stdout (default)**:
```
https://www.dropbox.com/scl/fi/abc123/Meeting+Notes.paper?rlkey=xxx
```

**Stdout (`--json`)**:
```json
{
  "url": "https://www.dropbox.com/scl/fi/abc123/Meeting+Notes.paper?rlkey=xxx",
  "name": "Meeting Notes.paper",
  "id": "id:abc123"
}
```

---

## Command Group: `cache`

### `paper cache sync`

Sync the Dropbox directory tree metadata to the local SQLite cache.

```
paper cache sync [--full]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--full` | bool | `false` | Force a full resync (ignore saved cursor) |

**Stdout (default)**:
```
Syncing metadata...
  Added:   42 items
  Updated: 15 items
  Removed:  3 items
  Total:  1,247 items in cache

✓ Sync complete (3.2s)
```

**Stdout (`--json`)**:
```json
{
  "status": "synced",
  "added": 42,
  "updated": 15,
  "removed": 3,
  "total": 1247,
  "duration_seconds": 3.2,
  "sync_type": "incremental"
}
```

### `paper cache search`

Search file and folder names in the local cache by keyword.

```
paper cache search <QUERY> [--type <file|folder>] [--limit N]
```

| Argument/Flag | Type | Default | Description |
|---------------|------|---------|-------------|
| `QUERY` | string | required | Search keyword(s) |
| `--type` | enum | all | Filter by item type: `file` or `folder` |
| `--limit` | int | 50 | Maximum results to return |

**Stdout (default)**:
```
Found 3 results for "meeting":

📄 Meeting Notes.paper       /Project Notes/Meeting Notes.paper
📄 Team Meeting Agenda.paper /Shared/Team Meeting Agenda.paper
📁 Meeting Recordings/       /Archive/Meeting Recordings/
```

**Stdout (`--json`)**:
```json
{
  "query": "meeting",
  "results": [
    {
      "id": "id:abc123",
      "name": "Meeting Notes.paper",
      "path": "/Project Notes/Meeting Notes.paper",
      "type": "file"
    }
  ],
  "count": 3
}
```

---

## Command Group: `sharing`

### `paper sharing info`

Get sharing information for a shared folder.

```
paper sharing info <TARGET>
```

| Argument | Type | Description |
|----------|------|-------------|
| `TARGET` | string | Folder ID, path, or URL |

**Stdout (default)**:
```
Shared Folder: Project Notes
Folder ID:     sf:1234567890

Members:
  Jane Doe (jane@example.com)        owner
  Bob Smith (bob@example.com)        editor
  Alice Chen (alice@example.com)     viewer
```

**Stdout (`--json`)**:
```json
{
  "shared_folder_id": "sf:1234567890",
  "name": "Project Notes",
  "members": [
    {
      "display_name": "Jane Doe",
      "email": "jane@example.com",
      "access_type": "owner"
    }
  ]
}
```

---

## Input Resolution Contract

Any command argument that accepts a `TARGET` or file reference MUST resolve inputs in this order:

1. **Dropbox Paper URL**: If the input matches `https?://(?:www\.)?dropbox\.com/scl/fi/([^/]+)/.*`, extract the file ID.
2. **Dropbox ID**: If the input starts with `id:`, use as-is.
3. **Dropbox path**: Otherwise, treat as a Dropbox path (e.g., `/folder/file.paper`).

If URL parsing is attempted but fails, emit error code `URL_PARSE_ERROR` (exit code 4).
