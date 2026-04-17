# dropbox-paper-cli Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-18

## Active Technologies
- Python 3.12+ (required by constitution) + httpx (replaces dropbox SDK), typer (CLI framework, unchanged), textual (TUI, unchanged) (002-httpx-api-migration)
- SQLite via built-in `sqlite3` (metadata cache, unchanged) (002-httpx-api-migration)

- Python 3.12+ + Typer (CLI framework), dropbox (official Dropbox Python SDK) (001-paper-cli-v1)

## Project Structure

```text
src/
tests/
```

## Commands

cd src && pytest && ruff check .

## Code Style

Python 3.12+: Follow standard conventions

## Recent Changes
- 002-httpx-api-migration: Added Python 3.12+ (required by constitution) + httpx (replaces dropbox SDK), typer (CLI framework, unchanged), textual (TUI, unchanged)

- 001-paper-cli-v1: Added Python 3.12+ + Typer (CLI framework), dropbox (official Dropbox Python SDK)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
