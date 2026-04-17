"""Cache service: parallel sync with streaming, progress reporting, and FTS5 search."""

from __future__ import annotations

import sqlite3
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from queue import Empty, Queue

import dropbox
import dropbox.files

from dropbox_paper_cli.models.cache import CachedMetadata, SyncResult, SyncState

# Sentinel placed in queue by each worker on completion
_SENTINEL = object()

# Default max concurrent API fetchers
DEFAULT_CONCURRENCY = 20

# Items processed between progress callbacks / DB commits
_PROGRESS_INTERVAL = 500

ProgressCallback = Callable[[SyncResult], None]


class CacheService:
    """Manages local metadata cache sync and search operations.

    Uses parallel folder listing with streaming writes for fast, low-memory sync.
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

        Uses parallel folder listing (up to ``concurrency`` workers) with
        streaming writes for speed and low memory usage.

        Args:
            force_full: Ignore saved cursors and do a full resync.
            path: Dropbox path to sync (empty string for root).
            concurrency: Max concurrent API fetchers.
            on_progress: Called periodically with current SyncResult.
        """
        if path == "/":
            path = ""
        start = time.monotonic()
        progress = on_progress or (lambda _r: None)

        # If sync root changed, force full resync
        saved_root = self._load_meta("sync_root")
        if saved_root is not None and saved_root != path:
            force_full = True

        if not force_full and self._has_folder_cursors():
            result = self._incremental_sync_parallel(path, concurrency, progress)
            result.sync_type = "incremental"
        elif not force_full and self._load_sync_state().cursor:
            # Legacy single-cursor → force full parallel resync
            result = self._full_sync_parallel(path, concurrency, progress)
            result.sync_type = "full"
        else:
            result = self._full_sync_parallel(path, concurrency, progress)
            result.sync_type = "full"

        result.duration_seconds = round(time.monotonic() - start, 2)
        result.total = self._count_metadata()
        self._save_meta("sync_root", path)
        return result

    # ── Full Sync (Parallel) ─────────────────────────────────────

    def _full_sync_parallel(
        self,
        path: str,
        concurrency: int,
        on_progress: ProgressCallback,
    ) -> SyncResult:
        result = SyncResult()
        existing_ids = self._get_existing_ids()
        seen_ids: set[str] = set()

        # Phase 1: list top-level entries (non-recursive)
        top_entries, folders = self._list_top_level(path)

        # Process top-level entries immediately (files + folder metadata)
        for entry in top_entries:
            self._process_full_entry(entry, existing_ids, seen_ids, result)
        self._conn.commit()
        on_progress(result)

        if not folders:
            self._remove_unseen(existing_ids, seen_ids, result)
            self._clear_folder_cursors()
            self._save_sync_state(None, self._now_str())
            self._conn.commit()
            on_progress(result)
            return result

        # Phase 2: parallel recursive listing of each subfolder
        entry_queue: Queue = Queue(maxsize=5000)
        folder_cursors: dict[str, str] = {}
        worker_errors: list[tuple[str, Exception]] = []

        num_workers = min(concurrency, len(folders))
        worker_clients = self._create_worker_clients(num_workers)

        def worker(client: dropbox.Dropbox, folder_id: str, folder_path: str) -> None:
            try:
                res = client.files_list_folder(folder_path, recursive=True, limit=2000)
                for e in res.entries:
                    entry_queue.put(e)
                while res.has_more:
                    res = client.files_list_folder_continue(res.cursor)
                    for e in res.entries:
                        entry_queue.put(e)
                entry_queue.put((_SENTINEL, folder_id, res.cursor, None))
            except Exception as exc:
                entry_queue.put((_SENTINEL, folder_id, None, exc))

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            for i, folder in enumerate(folders):
                client = worker_clients[i % num_workers]
                pool.submit(worker, client, folder.id, folder.path_lower)

            # Consume queue on main thread — all DB writes stay single-threaded
            sentinels_received = 0
            while sentinels_received < len(folders):
                try:
                    item = entry_queue.get(timeout=1.0)
                except Empty:
                    continue

                if isinstance(item, tuple) and len(item) == 4 and item[0] is _SENTINEL:
                    _, fid, cursor, error = item
                    sentinels_received += 1
                    if error:
                        worker_errors.append((fid, error))
                    elif cursor:
                        folder_cursors[fid] = cursor
                    continue

                # Regular entry
                self._process_full_entry(item, existing_ids, seen_ids, result)
                total = result.added + result.updated
                if total % _PROGRESS_INTERVAL == 0:
                    self._conn.commit()
                    on_progress(result)

        # Remove entries no longer present
        self._remove_unseen(existing_ids, seen_ids, result)

        # Save per-folder cursors for successful workers;
        # failed folders simply get no cursor (will do full listing next time)
        now = self._now_str()
        self._clear_folder_cursors()
        for fid, cursor in folder_cursors.items():
            self._save_folder_cursor(fid, cursor)
        for fid, exc in worker_errors:
            print(f"[sync] Warning: folder {fid} failed: {exc}", file=sys.stderr)
        self._save_sync_state(None, now)
        self._conn.commit()
        on_progress(result)
        return result

    # ── Incremental Sync (Parallel) ──────────────────────────────

    def _incremental_sync_parallel(
        self,
        path: str,
        concurrency: int,
        on_progress: ProgressCallback,
    ) -> SyncResult:
        result = SyncResult()

        # Load saved folder cursors (keyed by folder ID)
        saved_cursors = self._load_folder_cursors()

        # List current top-level to detect new/deleted folders
        top_entries, folders = self._list_top_level(path)
        current_folder_ids = {f.id: f for f in folders}
        saved_folder_ids = set(saved_cursors.keys())

        new_folders = [f for f in folders if f.id not in saved_folder_ids]
        deleted_folder_ids = saved_folder_ids - set(current_folder_ids.keys())
        continuing = {fid: saved_cursors[fid] for fid in saved_folder_ids if fid in current_folder_ids}

        # Process top-level entries
        existing_ids = self._get_existing_ids()
        seen_ids: set[str] = set()
        for entry in top_entries:
            self._process_incremental_entry(entry, existing_ids, seen_ids, result)
        self._conn.commit()

        # Remove entries from deleted folders
        for fid in deleted_folder_ids:
            self._remove_entries_by_cursor_folder(fid, result)

        total_tasks = len(continuing) + len(new_folders)
        if total_tasks == 0:
            self._clear_folder_cursors()
            self._save_sync_state(None, self._now_str())
            self._conn.commit()
            on_progress(result)
            return result

        entry_queue: Queue = Queue(maxsize=5000)
        folder_cursors: dict[str, str] = {}
        worker_errors: list[tuple[str, Exception]] = []

        num_workers = min(concurrency, total_tasks)
        worker_clients = self._create_worker_clients(num_workers)

        def continue_worker(client: dropbox.Dropbox, folder_id: str, cursor: str) -> None:
            try:
                res = client.files_list_folder_continue(cursor)
                for e in res.entries:
                    entry_queue.put(e)
                while res.has_more:
                    res = client.files_list_folder_continue(res.cursor)
                    for e in res.entries:
                        entry_queue.put(e)
                entry_queue.put((_SENTINEL, folder_id, res.cursor, None))
            except dropbox.exceptions.ApiError as exc:
                if hasattr(exc.error, "is_reset") and exc.error.is_reset():
                    # Cursor expired — full listing for this folder
                    folder = current_folder_ids.get(folder_id)
                    if folder:
                        new_folder_worker(client, folder_id, folder.path_lower)
                    else:
                        entry_queue.put((_SENTINEL, folder_id, None, exc))
                else:
                    entry_queue.put((_SENTINEL, folder_id, None, exc))
            except Exception as exc:
                entry_queue.put((_SENTINEL, folder_id, None, exc))

        def new_folder_worker(client: dropbox.Dropbox, folder_id: str, folder_path: str) -> None:
            try:
                res = client.files_list_folder(folder_path, recursive=True, limit=2000)
                for e in res.entries:
                    entry_queue.put(e)
                while res.has_more:
                    res = client.files_list_folder_continue(res.cursor)
                    for e in res.entries:
                        entry_queue.put(e)
                entry_queue.put((_SENTINEL, folder_id, res.cursor, None))
            except Exception as exc:
                entry_queue.put((_SENTINEL, folder_id, None, exc))

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            task_idx = 0
            for fid, cursor in continuing.items():
                client = worker_clients[task_idx % num_workers]
                pool.submit(continue_worker, client, fid, cursor)
                task_idx += 1
            for folder in new_folders:
                client = worker_clients[task_idx % num_workers]
                pool.submit(new_folder_worker, client, folder.id, folder.path_lower)
                task_idx += 1

            sentinels_received = 0
            while sentinels_received < total_tasks:
                try:
                    item = entry_queue.get(timeout=1.0)
                except Empty:
                    continue

                if isinstance(item, tuple) and len(item) == 4 and item[0] is _SENTINEL:
                    _, fid, cursor, error = item
                    sentinels_received += 1
                    if error:
                        worker_errors.append((fid, error))
                    elif cursor:
                        folder_cursors[fid] = cursor
                    continue

                self._process_incremental_entry(item, existing_ids, seen_ids, result)
                total = result.added + result.updated + result.removed
                if total % _PROGRESS_INTERVAL == 0:
                    self._conn.commit()
                    on_progress(result)

        # Save cursors — successful folders get updated cursor,
        # failed folders get no cursor (will do full listing next time)
        now = self._now_str()
        self._clear_folder_cursors()
        for fid, cursor in folder_cursors.items():
            self._save_folder_cursor(fid, cursor)
        for fid, exc in worker_errors:
            print(f"[sync] Warning: folder {fid} failed: {exc}", file=sys.stderr)
        self._save_sync_state(None, now)
        self._conn.commit()
        on_progress(result)
        return result

    # ── Entry Processing ─────────────────────────────────────────

    def _process_full_entry(
        self,
        entry: object,
        existing_ids: set[str],
        seen_ids: set[str],
        result: SyncResult,
    ) -> None:
        cached = self._entry_to_cached(entry)
        if cached is None:
            return
        seen_ids.add(cached.id)
        if cached.id in existing_ids:
            result.updated += 1
        else:
            result.added += 1
        self._upsert_metadata(cached)

    def _process_incremental_entry(
        self,
        entry: object,
        existing_ids: set[str],
        seen_ids: set[str],
        result: SyncResult,
    ) -> None:
        if isinstance(entry, dropbox.files.DeletedMetadata):
            deleted = self._conn.execute(
                "SELECT id FROM metadata WHERE path_lower = ?",
                (entry.path_lower,),
            ).fetchone()
            if deleted:
                self._conn.execute("DELETE FROM metadata WHERE id = ?", (deleted[0],))
                result.removed += 1
            return
        self._process_full_entry(entry, existing_ids, seen_ids, result)

    # ── Top-Level Listing ────────────────────────────────────────

    def _list_top_level(self, path: str) -> tuple[list, list]:
        """List top-level entries (non-recursive), returning (all_entries, folder_entries)."""
        result = self._dbx.files_list_folder(path, recursive=False, limit=2000)
        entries = list(result.entries)
        while result.has_more:
            result = self._dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)
        folders = [e for e in entries if isinstance(e, dropbox.files.FolderMetadata)]
        return entries, folders

    # ── Worker Client Management ─────────────────────────────────

    def _create_worker_clients(self, n: int) -> list[dropbox.Dropbox]:
        """Create per-thread Dropbox clients for safe concurrent access."""
        if self._client_factory:
            return [self._client_factory() for _ in range(n)]
        # Fallback: clone main client with new HTTP sessions
        return [self._dbx.clone(session=dropbox.create_session()) for _ in range(n)]

    # ── Entry Conversion ─────────────────────────────────────────

    def _entry_to_cached(self, entry: object) -> CachedMetadata | None:  # noqa: ANN001
        """Convert a Dropbox SDK entry to a CachedMetadata."""
        if isinstance(entry, dropbox.files.DeletedMetadata):
            return None

        is_dir = isinstance(entry, dropbox.files.FolderMetadata)

        path_lower = entry.path_lower
        parent_path = None
        if "/" in path_lower and path_lower != "/":
            parent_path = path_lower.rsplit("/", 1)[0] or "/"

        server_modified = None
        if hasattr(entry, "server_modified") and entry.server_modified:
            server_modified = (
                entry.server_modified.isoformat()
                if hasattr(entry.server_modified, "isoformat")
                else str(entry.server_modified)
            )

        return CachedMetadata(
            id=entry.id,
            name=entry.name,
            path_display=entry.path_display,
            path_lower=entry.path_lower,
            is_dir=is_dir,
            parent_path=parent_path,
            size_bytes=getattr(entry, "size", None) if not is_dir else None,
            server_modified=server_modified if not is_dir else None,
            rev=getattr(entry, "rev", None) if not is_dir else None,
            content_hash=getattr(entry, "content_hash", None) if not is_dir else None,
        )

    def _upsert_metadata(self, cached: CachedMetadata) -> None:
        """Insert or replace a metadata entry."""
        self._conn.execute(
            """INSERT OR REPLACE INTO metadata
            (id, name, path_display, path_lower, is_dir, parent_path,
             size_bytes, server_modified, rev, content_hash, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            cached.to_row(),
        )

    # ── Delete Detection ─────────────────────────────────────────

    def _get_existing_ids(self) -> set[str]:
        return {row[0] for row in self._conn.execute("SELECT id FROM metadata").fetchall()}

    def _remove_unseen(
        self, existing_ids: set[str], seen_ids: set[str], result: SyncResult
    ) -> None:
        removed_ids = existing_ids - seen_ids
        for rid in removed_ids:
            self._conn.execute("DELETE FROM metadata WHERE id = ?", (rid,))
            result.removed += 1

    def _remove_entries_by_cursor_folder(self, folder_id: str, result: SyncResult) -> None:
        """Remove cached entries for a folder that no longer exists.

        Since we track cursors by folder ID, we look up the folder's path
        from the metadata table and delete everything under it.
        """
        row = self._conn.execute(
            "SELECT path_lower FROM metadata WHERE id = ?", (folder_id,)
        ).fetchone()
        if row:
            folder_path = row[0]
            count = self._conn.execute(
                "DELETE FROM metadata WHERE path_lower LIKE ? OR path_lower = ?",
                (folder_path + "/%", folder_path),
            ).rowcount
            result.removed += count

    # ── Sync State Management ────────────────────────────────────

    def _count_metadata(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM metadata").fetchone()[0]

    def _load_sync_state(self) -> SyncState:
        row = self._conn.execute(
            "SELECT key, cursor, last_sync_at, total_items FROM sync_state WHERE key = ?",
            ("default",),
        ).fetchone()
        if row:
            return SyncState(key=row[0], cursor=row[1], last_sync_at=row[2], total_items=row[3])
        return SyncState()

    def _save_sync_state(self, cursor: str | None, last_sync_at: str) -> None:
        total = self._count_metadata()
        self._conn.execute(
            """INSERT OR REPLACE INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES (?, ?, ?, ?)""",
            ("default", cursor, last_sync_at, total),
        )

    # ── Per-Folder Cursor Management ─────────────────────────────

    def _has_folder_cursors(self) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM sync_state WHERE key LIKE 'cursor:%'"
        ).fetchone()
        return row[0] > 0

    def _load_folder_cursors(self) -> dict[str, str]:
        """Load folder cursors. Returns {folder_id: cursor}."""
        rows = self._conn.execute(
            "SELECT key, cursor FROM sync_state WHERE key LIKE 'cursor:%'"
        ).fetchall()
        return {row[0][len("cursor:"):]: row[1] for row in rows if row[1]}

    def _save_folder_cursor(self, folder_id: str, cursor: str) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES (?, ?, ?, 0)""",
            (f"cursor:{folder_id}", cursor, self._now_str()),
        )

    def _clear_folder_cursors(self) -> None:
        self._conn.execute("DELETE FROM sync_state WHERE key LIKE 'cursor:%'")

    # ── Meta Key-Value Storage ───────────────────────────────────

    def _load_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT cursor FROM sync_state WHERE key = ?",
            (f"meta:{key}",),
        ).fetchone()
        return row[0] if row else None

    def _save_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES (?, ?, ?, 0)""",
            (f"meta:{key}", value, self._now_str()),
        )

    @staticmethod
    def _now_str() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

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
        m.parent_path, m.size_bytes, m.server_modified, m.rev,
        m.content_hash, m.synced_at
    """

    def _type_clause(self, item_type: str | None) -> str:
        if item_type == "file":
            return "AND m.is_dir = 0"
        if item_type == "folder":
            return "AND m.is_dir = 1"
        return ""

    def _fts_search(
        self, query: str, item_type: str | None, limit: int
    ) -> list[tuple]:
        type_clause = self._type_clause(item_type)
        sql = f"""
            SELECT {self._SELECT_COLS}
            FROM metadata m
            JOIN metadata_fts ON m.rowid = metadata_fts.rowid
            WHERE metadata_fts MATCH ? {type_clause}
            LIMIT ?
        """
        return self._conn.execute(sql, (query, limit)).fetchall()

    def _like_search(
        self, query: str, item_type: str | None, limit: int
    ) -> list[tuple]:
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
