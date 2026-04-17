# Contract: RPC Endpoints

**Feature**: 002-httpx-api-migration
**Date**: 2025-07-15

All RPC endpoints use the same request/response pattern:

```
POST https://api.dropboxapi.com/2/{endpoint}
Authorization: Bearer {access_token}
Content-Type: application/json
Dropbox-API-Path-Root: {".tag": "root", "root": "{ns_id}"}  # optional, team accounts only

{json_params}
```

**Success Response**: `200 OK` with JSON body
**Error Response**: `409 Conflict` with JSON error body (Dropbox-specific), or standard HTTP errors (400, 401, 403, 429, 500, 503)

---

## File & Folder Operations

### files/list_folder

```
POST /2/files/list_folder
```

**Request**:
```json
{
    "path": "",
    "recursive": false,
    "limit": 2000
}
```

**Response**:
```json
{
    "entries": [
        {
            ".tag": "file",
            "id": "id:abc123",
            "name": "document.paper",
            "path_display": "/Documents/document.paper",
            "path_lower": "/documents/document.paper",
            "size": 1024,
            "server_modified": "2025-01-15T10:30:00Z",
            "rev": "015f...",
            "content_hash": "e3b0..."
        },
        {
            ".tag": "folder",
            "id": "id:def456",
            "name": "Subfolder",
            "path_display": "/Documents/Subfolder",
            "path_lower": "/documents/subfolder"
        }
    ],
    "cursor": "AAF...",
    "has_more": true
}
```

**Pagination**: When `has_more` is true, call `files/list_folder/continue` with the cursor.

### files/list_folder/continue

```
POST /2/files/list_folder/continue
```

**Request**:
```json
{
    "cursor": "AAF..."
}
```

**Response**: Same schema as `files/list_folder`.

**Cursor Reset**: If the cursor is too old, the API returns a 409 with `error_summary` containing `reset`. The client must restart with a fresh `list_folder` call.

### files/get_metadata

```
POST /2/files/get_metadata
```

**Request**:
```json
{
    "path": "/Documents/document.paper",
    "include_media_info": false,
    "include_deleted": false,
    "include_has_explicit_shared_members": false
}
```

**Response**: Single entry object (same schema as entries in list_folder).

**Error (409)**:
```json
{
    "error_summary": "path/not_found/...",
    "error": { ".tag": "path", "path": { ".tag": "not_found" } }
}
```

### files/move_v2

```
POST /2/files/move_v2
```

**Request**:
```json
{
    "from_path": "/old/path",
    "to_path": "/new/path",
    "autorename": false
}
```

**Response**:
```json
{
    "metadata": { /* entry object */ }
}
```

### files/copy_v2

```
POST /2/files/copy_v2
```

**Request/Response**: Same schema as `files/move_v2`.

### files/delete_v2

```
POST /2/files/delete_v2
```

**Request**:
```json
{
    "path": "/path/to/item"
}
```

**Response**:
```json
{
    "metadata": { /* entry object */ }
}
```

### files/create_folder_v2

```
POST /2/files/create_folder_v2
```

**Request**:
```json
{
    "path": "/path/to/new-folder",
    "autorename": false
}
```

**Response**:
```json
{
    "metadata": { /* folder entry object */ }
}
```

---

## Sharing Operations

### sharing/create_shared_link_with_settings

```
POST /2/sharing/create_shared_link_with_settings
```

**Request**:
```json
{
    "path": "/path/to/file",
    "settings": {
        "requested_visibility": { ".tag": "public" },
        "audience": { ".tag": "public" },
        "access": { ".tag": "viewer" }
    }
}
```

**Response**:
```json
{
    "url": "https://www.dropbox.com/scl/fi/...",
    "path_lower": "/path/to/file",
    "link_permissions": { /* ... */ }
}
```

**Conflict (409)**: If a link already exists, `error_summary` contains `shared_link_already_exists`. The response includes the existing link in the error structure.

### sharing/get_shared_link_metadata

```
POST /2/sharing/get_shared_link_metadata
```

**Request**:
```json
{
    "url": "https://www.dropbox.com/scl/fi/..."
}
```

**Response**: Returns metadata for the shared link target (file/folder entry object with `.tag`, `id`, `path_display`, etc.).

### sharing/get_folder_metadata

```
POST /2/sharing/get_folder_metadata
```

**Request**:
```json
{
    "shared_folder_id": "84528192421"
}
```

**Response**:
```json
{
    "shared_folder_id": "84528192421",
    "name": "Shared Folder",
    "path_lower": "/shared folder",
    "access_type": { ".tag": "owner" }
}
```

### sharing/list_folder_members

```
POST /2/sharing/list_folder_members
```

**Request**:
```json
{
    "shared_folder_id": "84528192421",
    "limit": 200
}
```

**Response**:
```json
{
    "users": [
        {
            "access_type": { ".tag": "editor" },
            "user": {
                "account_id": "dbid:AAB...",
                "display_name": "Jane Doe",
                "email": "jane@example.com"
            },
            "is_inherited": false
        }
    ],
    "cursor": "ZtkX...",
    "has_more": false,
    "invitees": [],
    "groups": []
}
```

**Pagination**: When `has_more` is `true`, call `sharing/list_folder_members/continue` with the `cursor` value.

### sharing/list_folder_members/continue

```
POST /2/sharing/list_folder_members/continue
```

**Request**:
```json
{
    "cursor": "ZtkX..."
}
```

**Response**: Same schema as `sharing/list_folder_members`.

---

## User Operations

### users/get_current_account

```
POST /2/users/get_current_account
```

**Request**: `null` (empty body or `null`)

**Response**:
```json
{
    "account_id": "dbid:AAB...",
    "name": {
        "display_name": "Jane Doe",
        "abbreviated_name": "JD"
    },
    "email": "jane@example.com",
    "root_info": {
        ".tag": "team",
        "root_namespace_id": "123456789",
        "home_namespace_id": "987654321"
    }
}
```

**Team Detection**: When `root_info[".tag"]` is `"team"`, extract `root_namespace_id` and `home_namespace_id` for the `Dropbox-API-Path-Root` header.

---

## Error Response Schema (all RPC endpoints)

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

### Error Mapping

| HTTP Status | error_summary pattern | Maps To |
|-------------|----------------------|---------|
| 409 | `path/not_found` | `NotFoundError` |
| 409 | `path/conflict` | `ValidationError` |
| 409 | `from_lookup/not_found` | `NotFoundError` |
| 409 | `access_error` | `PermissionError` |
| 409 | `shared_link_already_exists` | Return existing link (special handling) |
| 409 | `non_exportable` | `ValidationError("Not a Paper document")` |
| 409 | `invalid_file_extension` | `ValidationError("Path must end with .paper")` |
| 409 | `email_unverified` | `ValidationError("Email must be verified")` |
| 409 | `paper_disabled` | `ValidationError("Paper is disabled for this team")` |
| 409 | `doc_archived` | `ValidationError("Document is archived")` |
| 409 | `doc_deleted` | `NotFoundError("Document is deleted")` |
| 409 | `revision_mismatch` | `ValidationError("Revision mismatch")` |
| 400 | (any) | `ValidationError` |
| 401 | (any) | Token refresh → retry |
| 403 | (any) | `PermissionError` |
| 429 | (any) | Retry with `Retry-After` header |
| 500, 503 | (any) | Retry with exponential backoff |
