# dropbox-paper-cli

A Python CLI tool for managing Dropbox Paper documents from the terminal — browse files, read Paper docs as Markdown, and search across your entire workspace with a local metadata cache.

## Features

- **OAuth2 Authentication** — PKCE flow with automatic token refresh
- **File Operations** — list, read, move, copy, delete, create folders, get sharing links
- **Paper Doc Export** — read Paper documents as Markdown directly in your terminal
- **Local Cache & Search** — sync your full Dropbox directory tree to a local SQLite database for instant keyword search (FTS5 + CJK fallback)
- **Parallel Sync** — 20-concurrent-worker pipeline for large workspaces (tested with 59K+ items)
- **Team Account Support** — automatic namespace detection for Dropbox Business accounts
- **JSON Output** — `--json` flag on all commands for scripting

## Installation

Requires Python 3.12+.

```bash
# Install with uv (recommended)
uv tool install .

# Or with pip
pip install .
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

# 2. Sync metadata cache
paper cache sync

# 3. Search for documents
paper cache search "meeting notes"

# 4. Read a Paper document
paper files read "/path/to/document.paper"
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
paper files link PATH                # Get/create sharing link
paper files create-folder PATH       # Create a new folder
paper files move SRC DST             # Move file or folder
paper files copy SRC DST             # Copy file or folder
paper files delete PATH              # Delete file or folder
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
```

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

## Data Storage

Follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/):

| Purpose | Default Path | Override |
|---------|-------------|----------|
| Config (config.json, tokens) | `~/.config/dropbox-paper-cli/` | `PAPER_CLI_CONFIG_DIR` |
| Data (cache DB) | `~/.local/share/dropbox-paper-cli/` | `PAPER_CLI_DATA_DIR` |

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

## License

MIT
