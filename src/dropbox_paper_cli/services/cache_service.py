"""Cache service: sync facade and FTS5 search."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import dropbox

from dropbox_paper_cli.models.cache import CachedMetadata, SyncResult
from dropbox_paper_cli.services.sync_orchestrator import (
    DEFAULT_CONCURRENCY,
    ProgressCallback,
    SyncOrchestrator,
)


class CacheService:
    """Manages local metadata cache sync and search operations.

    Delegates parallel sync to SyncOrchestrator.
    SQLite FTS5 for keyword search with LIKE fallback for CJK.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        client: dropbox.Dropbox,
        *,
        client_factory: Callable[[], dropbox.Dropbox] | None = None,
    ) -> None:
        self._conn = conn
        self._dbx = client
        self._client_factory = client_factory

    # ── Sync Operations ───────────────────────────────────────────

    def sync(
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
        orchestrator = SyncOrchestrator(self._conn, self._dbx, client_factory=self._client_factory)
        return orchestrator.sync(
            force_full=force_full,
            path=path,
            concurrency=concurrency,
            on_progress=on_progress,
        )

    # ── Search Operations ─────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        item_type: str | None = None,
        limit: int = 50,
    ) -> list[CachedMetadata]:
        """Search file and folder names using FTS5, with LIKE fallback for CJK.

        FTS5's unicode61 tokenizer does not segment CJK characters, so when
        FTS returns no results the search transparently falls back to a
        LIKE-based substring match on name and path.

        Args:
            query: Search keyword(s).
            item_type: Filter by 'file' or 'folder'. None for all.
            limit: Maximum results.

        Returns:
            List of matching CachedMetadata entries.
        """
        fts_query = query.strip()
        if not fts_query:
            return []

        rows = self._fts_search(fts_query, item_type, limit)
        if not rows:
            rows = self._like_search(fts_query, item_type, limit)
        return [CachedMetadata.from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # Internal search helpers
    # ------------------------------------------------------------------

    _SELECT_COLS = """
        m.id, m.name, m.path_display, m.path_lower, m.is_dir,
        m.item_type, m.parent_path, m.size_bytes, m.server_modified, m.rev,
        m.content_hash, m.synced_at
    """

    def _type_clause(self, item_type: str | None) -> str:
        if item_type == "paper":
            return "AND m.item_type = 'paper'"
        if item_type == "file":
            return "AND m.item_type = 'file'"
        if item_type == "folder":
            return "AND m.item_type = 'folder'"
        return ""

    def _fts_search(self, query: str, item_type: str | None, limit: int) -> list[tuple]:
        type_clause = self._type_clause(item_type)
        sql = f"""
            SELECT {self._SELECT_COLS}
            FROM metadata m
            JOIN metadata_fts ON m.rowid = metadata_fts.rowid
            WHERE metadata_fts MATCH ? {type_clause}
            LIMIT ?
        """
        return self._conn.execute(sql, (query, limit)).fetchall()

    def _like_search(self, query: str, item_type: str | None, limit: int) -> list[tuple]:
        """Fallback substring search — works with CJK and any Unicode."""
        type_clause = self._type_clause(item_type)
        pattern = f"%{query}%"
        sql = f"""
            SELECT {self._SELECT_COLS}
            FROM metadata m
            WHERE (m.name LIKE ? OR m.path_display LIKE ?) {type_clause}
            LIMIT ?
        """
        return self._conn.execute(sql, (pattern, pattern, limit)).fetchall()
