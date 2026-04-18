"""Cache service: sync facade and FTS5 search."""

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
    m.content_hash, m.synced_at
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
    """Search file and folder names using FTS5, with LIKE fallback for CJK.

    FTS5's unicode61 tokenizer does not segment CJK characters, so when
    FTS returns no results the search transparently falls back to a
    LIKE-based substring match on name and path.
    """
    fts_query = query.strip()
    if not fts_query:
        return []

    tc = _type_clause(item_type)
    # Try FTS5 first
    rows = conn.execute(
        f"""
        SELECT {_SELECT_COLS}
        FROM metadata m
        JOIN metadata_fts ON m.rowid = metadata_fts.rowid
        WHERE metadata_fts MATCH ? {tc}
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    if not rows:
        # Fallback: LIKE substring search (works for CJK)
        pattern = f"%{fts_query}%"
        rows = conn.execute(
            f"""
            SELECT {_SELECT_COLS}
            FROM metadata m
            WHERE (m.name LIKE ? OR m.path_display LIKE ?) {tc}
            LIMIT ?
            """,
            (pattern, pattern, limit),
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
        orchestrator = SyncOrchestrator(self._conn, self._client)
        return await orchestrator.sync(
            force_full=force_full,
            path=path,
            concurrency=concurrency,
            on_progress=on_progress,
        )
