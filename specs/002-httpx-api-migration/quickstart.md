# Quickstart: 002-httpx-api-migration

**Feature**: Replace Dropbox SDK with Direct HTTP API + httpx
**Branch**: `002-httpx-api-migration`

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager

## Setup

```bash
# Clone and checkout the feature branch
git checkout 002-httpx-api-migration

# Install dependencies (uv will update the lockfile)
uv sync --dev

# Verify the environment
uv run python -c "import httpx; print(f'httpx {httpx.__version__}')"
uv run python -c "import typer; print(f'typer {typer.__version__}')"
```

## Key Files to Understand

Start with these files in reading order:

1. **`src/dropbox_paper_cli/lib/http_client.py`** (NEW) — The central async HTTP client. This is the core of the migration. Understand the three request methods (`rpc()`, `content_download()`, `content_upload()`), the token refresh logic, and the error mapping.

2. **`src/dropbox_paper_cli/lib/retry.py`** (MODIFIED) — Async retry decorator. Changed from sync to async, now catches httpx exceptions instead of SDK exceptions.

3. **`src/dropbox_paper_cli/services/dropbox_service.py`** (REWRITTEN) — All service methods are now `async def`. Each method calls `self._client.rpc()` or `self._client.content_*()` instead of `self._dbx.files_*()`.

4. **`src/dropbox_paper_cli/services/auth_service.py`** (REWRITTEN) — OAuth2 PKCE and auth code flows implemented via direct HTTP. Token refresh delegated to DropboxHttpClient.

5. **`src/dropbox_paper_cli/services/sync_orchestrator.py`** (REWRITTEN) — ThreadPoolExecutor replaced with `asyncio.gather()` + `asyncio.Semaphore(20)`.

6. **`src/dropbox_paper_cli/models/items.py`** (MODIFIED) — `from_sdk()` → `from_api()` for constructing models from JSON dicts.

7. **`src/dropbox_paper_cli/cli/common.py`** (MODIFIED) — Service factories now return async-ready services. New `async_command()` helper wraps `asyncio.run()`.

## Running Tests

```bash
# Run all unit tests
uv run pytest tests/unit/ -v

# Run specific test modules (most impacted by migration)
uv run pytest tests/unit/lib/test_http_client.py -v      # NEW: HTTP client tests
uv run pytest tests/unit/lib/test_retry.py -v             # Async retry tests
uv run pytest tests/unit/services/ -v                     # All service tests
uv run pytest tests/unit/models/test_items.py -v          # from_api() tests
uv run pytest tests/unit/models/test_sharing.py -v        # from_api() tests

# Run integration smoke tests (requires DROPBOX_PAPER_CLI_INTEGRATION=1)
DROPBOX_PAPER_CLI_INTEGRATION=1 uv run pytest tests/integration/ -v

# Run with verbose output to see HTTP logging
PAPER_LOG_LEVEL=DEBUG uv run pytest tests/unit/services/ -v
```

## Linting & Type Checking

```bash
# Ruff (linting + formatting)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type checking
uv run ty check src/
```

## Architecture Diagram

```
┌─────────────────────────────┐
│     Typer CLI Commands      │  ← sync entry points
│  asyncio.run(_async_impl)   │
└──────────┬──────────────────┘
           │
┌──────────▼──────────────────┐
│    Service Layer (async)     │
│  DropboxService              │
│  AuthService                 │
│  SharingService              │
│  SyncOrchestrator            │
│  CacheService                │
└──────────┬──────────────────┘
           │
┌──────────▼──────────────────┐
│   DropboxHttpClient (async)  │
│  ┌──────────────────────┐   │
│  │  httpx.AsyncClient   │   │  ← connection pooling
│  │  (single instance)   │   │
│  └──────────────────────┘   │
│  ┌──────────┐ ┌───────────┐ │
│  │  Token   │ │  Retry    │ │  ← asyncio.Lock + backoff
│  │  Refresh │ │  Logic    │ │
│  └──────────┘ └───────────┘ │
└──────────┬──────────────────┘
           │
    ┌──────┴──────┐
    │  Dropbox    │
    │  HTTP API   │
    │  v2         │
    └─────────────┘
```

## Common Patterns

### Adding a new API endpoint

```python
# In services/dropbox_service.py
@with_retry()
async def new_operation(self, path: str) -> DropboxItem:
    data = await self._client.rpc("files/new_operation", {"path": path})
    return DropboxItem.from_api(data)
```

### Testing with httpx mocks

```python
# In tests, use httpx mock responses
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_list_folder():
    mock_client = AsyncMock()
    mock_client.rpc.return_value = {
        "entries": [
            {".tag": "file", "id": "id:1", "name": "test.paper", ...}
        ],
        "has_more": False
    }
    svc = DropboxService(mock_client)
    items = await svc.list_folder("/test")
    assert len(items) == 1
    assert items[0].name == "test.paper"
```

## Migration Checklist

- [ ] `httpx` added to dependencies, `dropbox` removed
- [ ] `pytest-httpx` added to dev dependencies
- [ ] All `from_sdk()` replaced with `from_api()`
- [ ] All service methods are `async def`
- [ ] All CLI commands use `asyncio.run()` bridge
- [ ] Retry decorator is async-aware
- [ ] Token refresh uses `asyncio.Lock` double-check
- [ ] Sync orchestrator uses `asyncio.gather()` + `Semaphore`
- [ ] All tests pass with `uv run pytest`
- [ ] No `import dropbox` anywhere in codebase
- [ ] DEBUG-level HTTP logging works with `--verbose`
