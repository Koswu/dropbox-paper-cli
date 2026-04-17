"""Sync orchestrator: parallel full & incremental Dropbox metadata sync."""

from __future__ import annotations

import sqlite3
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from queue import Empty, Queue

import dropbox
import dropbox.exceptions
import dropbox.files

from dropbox_paper_cli.models.cache import CachedMetadata, SyncResult, SyncState

_SENTINEL = object()

DEFAULT_CONCURRENCY = 20
_PROGRESS_INTERVAL = 500

ProgressCallback = Callable[[SyncResult], None]


class SyncOrchestrator:
    """Orchestrates parallel folder listing with streaming DB writes."""

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

    # ── Public Entry Point ────────────────────────────────────────

    def sync(
        self,
        *,
        force_full: bool = False,
        path: str = "",
        concurrency: int = DEFAULT_CONCURRENCY,
        on_progress: ProgressCallback | None = None,
    ) -> SyncResult:
        """Run a full or incremental sync and return the result."""
        if path == "/":
            path = ""
        start = time.monotonic()
        progress = on_progress or (lambda _r: None)

        saved_root = self._load_meta("sync_root")
        if saved_root is not None and saved_root != path:
            force_full = True

        if not force_full and self._has_folder_cursors():
            result = self._incremental_sync_parallel(path, concurrency, progress)
            result.sync_type = "incremental"
        elif not force_full and self._load_sync_state().cursor:
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

        top_entries, folders = self._list_top_level(path)

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

                self._process_full_entry(item, existing_ids, seen_ids, result)
                total = result.added + result.updated
                if total % _PROGRESS_INTERVAL == 0:
                    self._conn.commit()
                    on_progress(result)

        self._remove_unseen(existing_ids, seen_ids, result)

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

        saved_cursors = self._load_folder_cursors()

        top_entries, folders = self._list_top_level(path)
        current_folder_ids = {f.id: f for f in folders}
        saved_folder_ids = set(saved_cursors.keys())

        new_folders = [f for f in folders if f.id not in saved_folder_ids]
        deleted_folder_ids = saved_folder_ids - set(current_folder_ids.keys())
        continuing = {
            fid: saved_cursors[fid] for fid in saved_folder_ids if fid in current_folder_ids
        }

        existing_ids = self._get_existing_ids()
        seen_ids: set[str] = set()
        for entry in top_entries:
            self._process_incremental_entry(entry, existing_ids, seen_ids, result)
        self._conn.commit()

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
        return [self._dbx.clone(session=dropbox.create_session()) for _ in range(n)]

    # ── Entry Conversion ─────────────────────────────────────────

    def _entry_to_cached(self, entry: object) -> CachedMetadata | None:
        """Convert a Dropbox SDK entry to a CachedMetadata."""
        if isinstance(entry, dropbox.files.DeletedMetadata):
            return None
        if not isinstance(entry, (dropbox.files.FileMetadata, dropbox.files.FolderMetadata)):
            return None

        is_dir = isinstance(entry, dropbox.files.FolderMetadata)

        if is_dir:
            item_type = "folder"
        elif entry.name.endswith(".paper"):
            item_type = "paper"
        else:
            item_type = "file"

        path_lower = entry.path_lower or ""
        parent_path = None
        if "/" in path_lower and path_lower != "/":
            parent_path = path_lower.rsplit("/", 1)[0] or "/"

        server_modified = None
        if isinstance(entry, dropbox.files.FileMetadata) and entry.server_modified:
            sm = entry.server_modified
            server_modified = sm.isoformat() if isinstance(sm, datetime) else str(sm)

        return CachedMetadata(
            id=entry.id,
            name=entry.name,
            path_display=entry.path_display,
            path_lower=entry.path_lower,
            is_dir=is_dir,
            item_type=item_type,
            parent_path=parent_path,
            size_bytes=entry.size if isinstance(entry, dropbox.files.FileMetadata) else None,
            server_modified=server_modified if not is_dir else None,
            rev=entry.rev if isinstance(entry, dropbox.files.FileMetadata) else None,
            content_hash=entry.content_hash
            if isinstance(entry, dropbox.files.FileMetadata)
            else None,
        )

    def _upsert_metadata(self, cached: CachedMetadata) -> None:
        """Insert or replace a metadata entry."""
        self._conn.execute(
            """INSERT OR REPLACE INTO metadata
            (id, name, path_display, path_lower, is_dir, item_type, parent_path,
             size_bytes, server_modified, rev, content_hash, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        """Remove cached entries for a folder that no longer exists."""
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
        return {row[0][len("cursor:") :]: row[1] for row in rows if row[1]}

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
