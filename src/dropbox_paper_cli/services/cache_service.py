"""Cache service: sync facade and LIKE-based search."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from dropbox_paper_cli.models.cache import CachedMetadata, SyncResult
from dropbox_paper_cli.services.sync_orchestrator import (
    DEFAULT_CONCURRENCY,
    ProgressCallback,
    SyncOrchestrator,
)

if TYPE_CHECKING:
    from dropbox_paper_cli.lib.http_client import DropboxHttpClient

# ── Standalone search (no HTTP client needed) ─────────────────────

_SELECT_COLS = """
    m.id, m.name, m.path_display, m.path_lower, m.is_dir,
    m.item_type, m.parent_path, m.size_bytes, m.server_modified, m.rev,
    m.content_hash, m.url, m.synced_at
"""


def _type_clause(item_type: str | None) -> str:
    if item_type == "paper":
        return "AND m.item_type = 'paper'"
    if item_type == "file":
        return "AND m.item_type = 'file'"
    if item_type == "folder":
        return "AND m.item_type = 'folder'"
    return ""


def search_cache(
    conn: sqlite3.Connection,
    query: str,
    *,
    item_type: str | None = None,
    limit: int = 50,
) -> list[CachedMetadata]:
    """Search file and folder names using LIKE substring match.

    Results are ordered by relevance: name matches first (shorter names
    ranked higher), then path-only matches.
    """
    q = query.strip()
    if not q:
        return []

    tc = _type_clause(item_type)
    pattern = f"%{q}%"
    rows = conn.execute(
        f"""
        SELECT {_SELECT_COLS}
        FROM metadata m
        WHERE (m.name LIKE ? OR m.path_display LIKE ?) {tc}
        ORDER BY
            (m.name LIKE ?) DESC,
            LENGTH(m.name)
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    return [CachedMetadata.from_row(row) for row in rows]


# ── Sync service (requires HTTP client) ──────────────────────────


class CacheService:
    """Manages local metadata cache sync operations.

    Delegates parallel sync to SyncOrchestrator.
    For search, use the standalone ``search_cache()`` function.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        client: DropboxHttpClient,
    ) -> None:
        self._conn = conn
        self._client = client

    @property
    def client(self) -> DropboxHttpClient:
        """Expose the HTTP client so callers can enter the async context."""
        return self._client

    async def sync(
        self,
        *,
        force_full: bool = False,
        path: str = "",
        concurrency: int = DEFAULT_CONCURRENCY,
        on_progress: ProgressCallback | None = None,
    ) -> SyncResult:
        """Sync Dropbox metadata to local cache.

        Delegates to SyncOrchestrator for parallel folder listing.
        """
        # Detect team account for correct web URL prefix
        token = self._client._token
        is_team = (
            token.root_namespace_id
            and token.home_namespace_id
            and token.root_namespace_id != token.home_namespace_id
        )
        url_base = "https://www.dropbox.com/work" if is_team else "https://www.dropbox.com/home"

        orchestrator = SyncOrchestrator(self._conn, self._client, url_base=url_base)
        return await orchestrator.sync(
            force_full=force_full,
            path=path,
            concurrency=concurrency,
            on_progress=on_progress,
        )
