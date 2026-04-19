# dropbox-paper-cli

[![PyPI](https://img.shields.io/pypi/v/dropbox-paper-cli)](https://pypi.org/project/dropbox-paper-cli/)
[![Python](https://img.shields.io/pypi/pyversions/dropbox-paper-cli)](https://pypi.org/project/dropbox-paper-cli/)
[![License: MIT](https://img.shields.io/pypi/l/dropbox-paper-cli)](https://github.com/Koswu/dropbox-paper-cli/blob/main/LICENSE)

A Python CLI tool for managing Dropbox Paper documents from the terminal — browse files, create and edit Paper docs, read as Markdown, search across your entire workspace with a local metadata cache, and interactively explore results in a TUI. Built on httpx for fully async HTTP communication.

## Features

- **OAuth2 Authentication** — PKCE flow with automatic token refresh
- **Async HTTP** — built on httpx with concurrent API requests and token auto-refresh
- **File Operations** — list, create, read, write, move, copy, delete, create folders, get sharing links
- **Paper Doc Creation** — create new Paper documents from Markdown, HTML, or plain text
- **Paper Doc Updates** — overwrite, append, prepend, or revision-safe update existing Paper documents
- **Paper Doc Export** — read Paper documents as Markdown directly in your terminal
- **Local Cache & Search** — sync your full Dropbox directory tree to a local SQLite database for instant keyword search (FTS5 + CJK fallback)
- **Paper Doc Discovery** — discovers all Paper 2.0 documents including those in team Paper folders
- **URL Resolution** — every cached item gets a web URL (constructed for files, sharing links for Paper docs)
- **Interactive TUI Search** — Textual-powered interactive search with F2 to copy link, F3 to open in browser
- **Adaptive Concurrency** — starts conservatively and ramps up, automatically backs off on 429 rate limits
- **Two-Level Parallel Sync** — expands top-level folders one level deep for dramatically higher parallelism (3x faster on large workspaces)
- **Rich Progress Display** — multi-phase progress bar showing metadata, preview URLs, and sharing link sync stages
- **Team Account Support** — automatic namespace detection for Dropbox Business accounts
- **Cross-Platform** — works on Linux, macOS, and Windows with platform-aware config paths
- **JSON Output** — `--json` flag on all commands for scripting
- **Verbose Logging** — `--verbose` flag for diagnostic output on all commands

## Installation

Requires Python 3.12+.

```bash
# Run directly with uvx (no install needed)
uvx dropbox-paper-cli --help

# Or install with uv (recommended)
uv tool install dropbox-paper-cli

# Or with pip
pip install dropbox-paper-cli
```

## Setup

### 1. Create a Dropbox App

Go to the [Dropbox App Console](https://www.dropbox.com/developers/apps) and create a new app:

- Choose **Scoped access**
- Choose **Full Dropbox** access type
- Give it any name you like

Under the **Permissions** tab, enable:
- `files.metadata.read`
- `files.content.read`
- `files.content.write`
- `sharing.read`
- `sharing.write`

### 2. Configure Credentials

Use the CLI to set your app credentials:

```bash
paper config set --app-key YOUR_APP_KEY
paper config set --app-secret YOUR_APP_SECRET  # optional
```

Or create the config file manually at `~/.config/dropbox-paper-cli/config.json`:

```json
{
    "app_key": "YOUR_APP_KEY",
    "app_secret": "YOUR_APP_SECRET"
}
```

`app_secret` is optional — if omitted, the PKCE flow is used (no secret needed, recommended for personal use).

Environment variables `DROPBOX_APP_KEY` / `DROPBOX_APP_SECRET` take priority over the config file.

### 3. Authenticate

```bash
paper auth login
```

Follow the browser prompt to authorize the app.

## Quick Start

```bash
# 1. Authenticate with Dropbox
paper auth login

# 2. Create a Paper document
echo "# My First Doc" | paper files create /My First Doc.paper

# 3. Read it back as Markdown
paper files read "/My First Doc.paper"

# 4. Sync metadata cache for search
paper cache sync

# 5. Search for documents
paper cache search "meeting notes"
```

## Commands

### Authentication

```bash
paper auth login     # OAuth2 login flow
paper auth logout    # Clear stored credentials
paper auth status    # Check authentication state
```

### Configuration

```bash
paper config set --app-key KEY       # Set Dropbox app key
paper config set --app-secret SECRET # Set Dropbox app secret
paper config show                    # Show current config
paper config path                    # Show config file path
```

### File Operations

```bash
paper files list [PATH]              # List files and folders
paper files metadata PATH            # Get detailed metadata
paper files read PATH                # Read Paper doc as Markdown
paper files create PATH              # Create a new Paper document
paper files write PATH               # Update a Paper document
paper files link PATH                # Get/create sharing link
paper files create-folder PATH       # Create a new folder
paper files move SRC DST             # Move file or folder
paper files copy SRC DST             # Copy file or folder
paper files delete PATH              # Delete file or folder
```

#### Creating Paper Documents

```bash
# From stdin (pipe-friendly)
echo "# Meeting Notes" | paper files create /notes/Meeting.paper

# From a local file
paper files create /notes/Meeting.paper --file notes.md

# HTML format
paper files create /doc.paper --format html --file page.html
```

#### Updating Paper Documents

```bash
# Overwrite entire content (default)
echo "# Updated" | paper files write /doc.paper

# Append content to end
echo "## Appendix" | paper files write /doc.paper --policy append

# Prepend content to beginning
echo "## Header" | paper files write /doc.paper --policy prepend

# Safe update with revision check (fails if doc changed since given revision)
paper files write /doc.paper --policy update --revision 5 --file new.md

# From a local file with format
paper files write /doc.paper --file content.md --format markdown
```

### Cache & Search

```bash
paper cache sync                     # Incremental sync (default)
paper cache sync --full              # Full resync
paper cache sync --path "/subfolder" # Sync specific subtree
paper cache sync --concurrency 10    # Custom worker count

paper cache search QUERY             # Search by keyword
paper cache search QUERY --type paper   # Filter: paper docs only
paper cache search QUERY --type folder  # Filter: folders only
paper cache search QUERY --type file    # Filter: regular files only
paper cache search QUERY --limit 20     # Limit results

paper cache isearch                  # Interactive TUI search
paper cache isearch "initial query"  # Open TUI with pre-filled query
```

**Interactive Search (TUI) Key Bindings:**

| Key | Action |
|-----|--------|
| Enter | Move focus to results table |
| F2 | Copy link to clipboard |
| F3 | Open in browser |
| Escape | Quit |

### Sharing

```bash
paper sharing info FOLDER_ID_OR_URL  # Get sharing info for a shared folder
```

### Global Options

```bash
paper --json ...      # JSON output for scripting
paper --verbose ...   # Diagnostic output to stderr
paper --version       # Show version
```

## Architecture

- **HTTP Layer**: httpx-based async client (`lib/http_client.py`) with automatic token refresh, retry with exponential backoff, and Dropbox API v2 RPC/content endpoints
- **Adaptive Concurrency**: `AdaptiveLimiter` starts at a conservative level, ramps up on success (+2), and backs off on 429 rate limits (ceiling × 0.7), settling at ceiling × 0.8
- **Services**: `DropboxService` (file/folder ops), `SharingService`, `SyncOrchestrator` (parallel sync with two-level expansion), standalone `search_cache()` for FTS5 queries
- **Sync Pipeline**: root listing → shallow expansion → parallel recursive on sub-folders, with per-folder cursors for efficient incremental sync
- **CLI**: Typer-based commands with `run_with_client()` helper for consistent async execution
- **TUI**: Textual-powered interactive search app with clipboard integration and browser launch
- **Cache**: SQLite with FTS5 full-text search, LIKE fallback for CJK, WAL mode, indexed `path_lower` for fast subtree operations

## Data Storage

Follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/):

| Purpose | Default Path | Override |
|---------|-------------|----------|
| Config (config.json, tokens) | `~/.config/dropbox-paper-cli/` | `PAPER_CLI_CONFIG_DIR` |
| Data (cache DB) | `~/.local/share/dropbox-paper-cli/` | `PAPER_CLI_DATA_DIR` |

## Development

```bash
# Clone and install dev dependencies
git clone https://github.com/Koswu/dropbox-paper-cli.git
cd dropbox-paper-cli
uv sync --group dev

# Run tests
uv run pytest

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run ty check

# Pre-commit hooks (ruff + ty)
uv run pre-commit install
uv run pre-commit run --all-files
```

## License

MIT
