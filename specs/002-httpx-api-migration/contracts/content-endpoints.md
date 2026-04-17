# Contract: Content-Download & Content-Upload Endpoints

**Feature**: 002-httpx-api-migration
**Date**: 2025-07-15

Content endpoints differ from RPC endpoints in how parameters and data are transmitted. Parameters go in the `Dropbox-API-Arg` header (JSON-encoded), and data goes in the request/response body.

---

## Common Headers

```
Authorization: Bearer {access_token}
Dropbox-API-Path-Root: {".tag": "root", "root": "{ns_id}"}  # optional, team accounts only
```

---

## Content-Download Endpoints

### files/export (Paper → Markdown)

Used to export Paper documents as Markdown.

```
POST https://content.dropboxapi.com/2/files/export
Authorization: Bearer {access_token}
Dropbox-API-Arg: {"path": "/path/to/document.paper", "export_format": "markdown"}
```

**Request Body**: Empty

**Response Headers**:
```
Dropbox-API-Result: {"export_metadata": {"name": "document.paper", "size": 1024, ...}, "file_metadata": { /* entry object */ }}
Content-Type: application/octet-stream
```

**Response Body**: Raw Markdown content (binary/text)

**Parsing**:
1. Read `Dropbox-API-Result` header → JSON decode → extract metadata
2. Read response body → decode as UTF-8 → Markdown string

**Timeout**: `CONTENT_TIMEOUT` (connect=5s, read=30s)

**Error Responses**: Same as RPC endpoints (JSON body with `error_summary`), but returned with standard HTTP error status codes.

---

## Content-Upload Endpoints

### files/paper/create

Used to create new Paper documents from Markdown/HTML/plain-text content.

```
POST https://content.dropboxapi.com/2/files/paper/create
Authorization: Bearer {access_token}
Content-Type: application/octet-stream
Dropbox-API-Arg: {"path": "/path/to/new-doc.paper", "import_format": {".tag": "markdown"}}
```

**Request Body**: Raw document content (UTF-8 encoded bytes)

**Dropbox-API-Arg Parameters**:
```json
{
    "path": "/path/to/new-doc.paper",
    "import_format": {
        ".tag": "markdown"
    }
}
```

**import_format values**: `"markdown"`, `"html"`, `"plain_text"`

**Response** (200 OK, JSON body):
```json
{
    "url": "https://www.dropbox.com/scl/fi/...",
    "result_path": "/path/to/new-doc.paper",
    "file_id": "id:abc123",
    "paper_revision": 1
}
```

**Timeout**: `CONTENT_TIMEOUT` (connect=5s, read=30s)

### files/paper/update

Used to update existing Paper documents.

```
POST https://content.dropboxapi.com/2/files/paper/update
Authorization: Bearer {access_token}
Content-Type: application/octet-stream
Dropbox-API-Arg: {"path": "/path/to/doc.paper", "import_format": {".tag": "markdown"}, "doc_update_policy": {".tag": "overwrite"}, "paper_revision": 1}
```

**Request Body**: Raw document content (UTF-8 encoded bytes)

**Dropbox-API-Arg Parameters**:
```json
{
    "path": "/path/to/doc.paper",
    "import_format": {
        ".tag": "markdown"
    },
    "doc_update_policy": {
        ".tag": "overwrite"
    },
    "paper_revision": 1
}
```

**doc_update_policy values**: `"overwrite"`, `"update"`, `"prepend"`, `"append"`

**paper_revision**: Optional. When provided, the API validates that the document hasn't been modified since this revision. Pass `None`/omit for unconditional overwrite.

**Response** (200 OK, JSON body):
```json
{
    "paper_revision": 2
}
```

**Timeout**: `CONTENT_TIMEOUT` (connect=5s, read=30s)

---

## Dropbox-API-Arg Header Encoding

The `Dropbox-API-Arg` header value is a JSON string. Characters outside the ASCII printable range (codepoints > 127) must be escaped using `\uXXXX` notation per the Dropbox API specification. This ensures HTTP header safety.

```python
import json

def encode_api_arg(params: dict) -> str:
    """Encode parameters for the Dropbox-API-Arg header."""
    raw = json.dumps(params, separators=(",", ":"))
    # Escape non-ASCII characters for HTTP header safety
    return "".join(
        c if ord(c) < 128 else f"\\u{ord(c):04x}"
        for c in raw
    )
```

---

## Timeout Profiles

| Profile | Connect | Read | Pool | Applied To |
|---------|---------|------|------|-----------|
| `METADATA_TIMEOUT` | 5s | 5s | 5s | All RPC endpoints |
| `CONTENT_TIMEOUT` | 5s | 30s | 5s | files/export, files/paper/create, files/paper/update |

```python
import httpx

METADATA_TIMEOUT = httpx.Timeout(5.0, connect=5.0, read=5.0, pool=5.0)
CONTENT_TIMEOUT = httpx.Timeout(30.0, connect=5.0, read=30.0, pool=5.0)
```
