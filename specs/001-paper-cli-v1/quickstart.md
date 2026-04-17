# Quickstart: Dropbox Paper CLI v1.0

**Date**: 2025-07-18
**Feature**: 001-paper-cli-v1

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed

## Setup

```bash
# Clone the repo
git clone <repo-url> dropbox-paper-cli
cd dropbox-paper-cli

# Install dependencies
uv sync

# Verify installation
uv run paper --help
```

## Authenticate

```bash
# Start OAuth2 PKCE flow (recommended)
uv run paper auth login

# Follow the browser prompt, paste the authorization code
# Token is stored at ~/.dropbox-paper-cli/tokens.json

# Verify authentication
uv run paper auth status
```

## Common Workflows

### Browse your Dropbox Paper files

```bash
# List root directory
uv run paper files list

# List a specific folder
uv run paper files list "/Project Notes"

# Get metadata for a file
uv run paper files metadata "/Project Notes/Meeting Notes.paper"

# Same thing with a Dropbox URL
uv run paper files metadata "https://www.dropbox.com/scl/fi/abc123/Meeting+Notes.paper?rlkey=xxx"
```

### Read a Paper document

```bash
# Output as Markdown to stdout
uv run paper files read "/Project Notes/Meeting Notes.paper"

# Pipe to a file
uv run paper files read "id:abc123" > meeting-notes.md

# JSON output with metadata
uv run paper --json files read "id:abc123"
```

### Organize files

```bash
# Create a folder
uv run paper files create-folder "/Archive/2025"

# Move a file
uv run paper files move "/Meeting Notes.paper" "/Archive/2025/Meeting Notes.paper"

# Copy a file
uv run paper files copy "/Template.paper" "/New Project/Template.paper"

# Delete a file
uv run paper files delete "/old-file.paper"

# Get a sharing link
uv run paper files link "/shared-doc.paper"
```

### Local search

```bash
# Sync metadata to local cache (first time: full sync)
uv run paper cache sync

# Search by keyword (sub-second, no API calls)
uv run paper cache search "meeting"

# Search only files
uv run paper cache search "notes" --type file

# Incremental sync (only fetches changes)
uv run paper cache sync
```

### Sharing info

```bash
# View shared folder members
uv run paper sharing info "/Shared Project"
```

## JSON Mode (for scripts and AI agents)

Every command supports `--json` for structured output:

```bash
# List files as JSON
uv run paper --json files list "/"

# Search and pipe to jq
uv run paper --json cache search "report" | jq '.results[].name'

# Error output is also JSON on stderr
uv run paper --json files metadata "/nonexistent" 2>&1
```

## Verbose Mode (for debugging)

```bash
# See HTTP calls, token refresh, cache operations on stderr
uv run paper --verbose files list "/"

# Combine with JSON (diagnostics on stderr, data on stdout)
uv run paper --json --verbose cache sync
```

## Development

```bash
# Run tests (TDD workflow)
uv run pytest

# Run tests with coverage
uv run pytest --cov=dropbox_paper_cli

# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/

# Type check
uv run ty check
```

## Project Structure

```
src/dropbox_paper_cli/
├── __init__.py
├── __main__.py              # Entry point: python -m dropbox_paper_cli
├── app.py                   # Main Typer app assembly
├── cli/                     # Command group modules
│   ├── __init__.py
│   ├── auth.py              # paper auth login/logout/status
│   ├── files.py             # paper files list/metadata/read/move/copy/delete/create-folder/link
│   ├── cache.py             # paper cache sync/search
│   └── sharing.py           # paper sharing info
├── services/                # Business logic layer
│   ├── __init__.py
│   ├── auth_service.py      # OAuth2 flows, token management
│   ├── dropbox_service.py   # SDK wrapper for file operations
│   ├── cache_service.py     # SQLite cache operations
│   └── sharing_service.py   # Sharing operations
├── models/                  # Data models
│   ├── __init__.py
│   ├── auth.py              # AuthToken
│   ├── items.py             # DropboxItem, PaperDocument
│   ├── sharing.py           # SharingInfo, MemberInfo
│   └── cache.py             # CachedMetadata, SyncState
├── lib/                     # Shared utilities
│   ├── __init__.py
│   ├── output.py            # OutputFormatter (JSON/human-readable)
│   ├── errors.py            # Error classes, exit codes
│   ├── retry.py             # Retry decorator with exponential backoff
│   ├── url_parser.py        # Dropbox URL → file ID extraction
│   └── config.py            # App configuration, paths
└── db/                      # Database layer
    ├── __init__.py
    ├── connection.py         # SQLite connection management
    └── schema.py             # Schema definition, migrations

tests/
├── conftest.py              # Shared fixtures (mock Dropbox client, CLI runner)
├── unit/
│   ├── cli/                 # CLI command tests
│   ├── services/            # Service layer tests
│   ├── models/              # Model tests
│   └── lib/                 # Utility tests
└── integration/             # Live API tests (opt-in)
```
