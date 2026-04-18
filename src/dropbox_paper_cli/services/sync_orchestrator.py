"""Sync orchestrator: async parallel full & incremental Dropbox metadata sync.

Uses asyncio.gather() + Semaphore(concurrency) instead of ThreadPoolExecutor.
All API calls go through a shared DropboxHttpClient (connection-pooled).
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dropbox_paper_cli.models.cache import CachedMetadata
from dropbox_paper_cli.models.sync import SyncResult, SyncState

if TYPE_CHECKING:
    from dropbox_paper_cli.lib.http_client import DropboxHttpClient

DEFAULT_CONCURRENCY = 20
_PROGRESS_INTERVAL = 500

ProgressCallback = Callable[[SyncResult], None]


class SyncOrchestrator:
    """Orchestrates parallel folder listing with streaming DB writes."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        client: DropboxHttpClient,
    ) -> None:
        self._conn = conn
        self._client = client

    # ── Public Entry Point ────────────────────────────────────────

    async def sync(
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
            result = await self._incremental_sync_parallel(path, concurrency, progress)
            result.sync_type = "incremental"
        else:
            result = await self._full_sync_parallel(path, concurrency, progress)
            result.sync_type = "full"
            # Fetch and cache sharing links on full sync
            result.links_cached = await self._sync_shared_links()

        result.duration_seconds = round(time.monotonic() - start, 2)
        result.total = self._count_metadata()
        self._save_meta("sync_root", path)
        return result

    # ── Full Sync (Parallel) ─────────────────────────────────────

    async def _full_sync_parallel(
        self,
        path: str,
        concurrency: int,
        on_progress: ProgressCallback,
    ) -> SyncResult:
        result = SyncResult()
        existing_ids = self._get_existing_ids()
        seen_ids: set[str] = set()

        top_entries, folders = await self._list_top_level(path)

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

        semaphore = asyncio.Semaphore(concurrency)
        folder_cursors: dict[str, str] = {}
        worker_errors: list[tuple[str, Exception]] = []
        lock = asyncio.Lock()

        async def list_folder_recursive(folder_id: str, folder_path: str) -> None:
            async with semaphore:
                try:
                    res = await self._client.rpc(
                        "files/list_folder",
                        {"path": folder_path, "recursive": True, "limit": 2000},
                    )
                    entries = list(res.get("entries", []))
                    while res.get("has_more"):
                        res = await self._client.rpc(
                            "files/list_folder/continue",
                            {"cursor": res["cursor"]},
                        )
                        entries.extend(res.get("entries", []))
                    async with lock:
                        for entry in entries:
                            self._process_full_entry(entry, existing_ids, seen_ids, result)
                        total = result.added + result.updated
                        if total % _PROGRESS_INTERVAL < len(entries):
                            self._conn.commit()
                            on_progress(result)
                        folder_cursors[folder_id] = res.get("cursor", "")
                except Exception as exc:
                    async with lock:
                        worker_errors.append((folder_id, exc))

        tasks = [list_folder_recursive(f["id"], f.get("path_lower", "")) for f in folders]
        await asyncio.gather(*tasks)

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

    async def _incremental_sync_parallel(
        self,
        path: str,
        concurrency: int,
        on_progress: ProgressCallback,
    ) -> SyncResult:
        result = SyncResult()

        saved_cursors = self._load_folder_cursors()

        top_entries, folders = await self._list_top_level(path)
        current_folder_ids = {f["id"]: f for f in folders}
        saved_folder_ids = set(saved_cursors.keys())

        new_folders = [f for f in folders if f["id"] not in saved_folder_ids]
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

        total_tasks_count = len(continuing) + len(new_folders)
        if total_tasks_count == 0:
            self._clear_folder_cursors()
            self._save_sync_state(None, self._now_str())
            self._conn.commit()
            on_progress(result)
            return result

        semaphore = asyncio.Semaphore(concurrency)
        folder_cursors: dict[str, str] = {}
        worker_errors: list[tuple[str, Exception]] = []
        lock = asyncio.Lock()

        async def continue_folder(folder_id: str, cursor: str) -> None:
            async with semaphore:
                try:
                    res = await self._client.rpc(
                        "files/list_folder/continue",
                        {"cursor": cursor},
                    )
                    entries = list(res.get("entries", []))
                    while res.get("has_more"):
                        res = await self._client.rpc(
                            "files/list_folder/continue",
                            {"cursor": res["cursor"]},
                        )
                        entries.extend(res.get("entries", []))
                    async with lock:
                        for entry in entries:
                            self._process_incremental_entry(entry, existing_ids, seen_ids, result)
                        folder_cursors[folder_id] = res.get("cursor", "")
                except Exception as exc:
                    # If cursor reset, do full listing for this folder
                    folder = current_folder_ids.get(folder_id)
                    if folder and "reset" in str(exc).lower():
                        await new_folder_listing(folder_id, folder.get("path_lower", ""))
                    else:
                        async with lock:
                            worker_errors.append((folder_id, exc))

        async def new_folder_listing(folder_id: str, folder_path: str) -> None:
            async with semaphore:
                try:
                    res = await self._client.rpc(
                        "files/list_folder",
                        {"path": folder_path, "recursive": True, "limit": 2000},
                    )
                    entries = list(res.get("entries", []))
                    while res.get("has_more"):
                        res = await self._client.rpc(
                            "files/list_folder/continue",
                            {"cursor": res["cursor"]},
                        )
                        entries.extend(res.get("entries", []))
                    async with lock:
                        for entry in entries:
                            self._process_incremental_entry(entry, existing_ids, seen_ids, result)
                        folder_cursors[folder_id] = res.get("cursor", "")
                except Exception as exc:
                    async with lock:
                        worker_errors.append((folder_id, exc))

        tasks = []
        for fid, cursor in continuing.items():
            tasks.append(continue_folder(fid, cursor))
        for folder in new_folders:
            tasks.append(new_folder_listing(folder["id"], folder.get("path_lower", "")))
        await asyncio.gather(*tasks)

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
        entry: dict[str, Any],
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
        entry: dict[str, Any],
        existing_ids: set[str],
        seen_ids: set[str],
        result: SyncResult,
    ) -> None:
        tag = entry.get(".tag", "")
        if tag == "deleted":
            path_lower = entry.get("path_lower", "")
            deleted = self._conn.execute(
                "SELECT id FROM metadata WHERE path_lower = ?",
                (path_lower,),
            ).fetchone()
            if deleted:
                self._conn.execute("DELETE FROM metadata WHERE id = ?", (deleted[0],))
                result.removed += 1
            return
        self._process_full_entry(entry, existing_ids, seen_ids, result)

    # ── Top-Level Listing ────────────────────────────────────────

    async def _list_top_level(self, path: str) -> tuple[list[dict], list[dict]]:
        """List top-level entries (non-recursive), returning (all_entries, folder_entries)."""
        res = await self._client.rpc(
            "files/list_folder",
            {"path": path, "recursive": False, "limit": 2000},
        )
        entries = list(res.get("entries", []))
        while res.get("has_more"):
            res = await self._client.rpc(
                "files/list_folder/continue",
                {"cursor": res["cursor"]},
            )
            entries.extend(res.get("entries", []))
        folders = [e for e in entries if e.get(".tag") == "folder"]
        return entries, folders

    # ── Shared-Link Sync ─────────────────────────────────────────

    async def _sync_shared_links(self) -> int:
        """Fetch all shared links and cache URLs by file ID. Returns count cached."""
        # Clear stale URLs so revoked links don't linger
        self._conn.execute("UPDATE metadata SET url = NULL WHERE url IS NOT NULL")

        count = 0
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            try:
                res = await self._client.rpc("sharing/list_shared_links", params or None)
            except Exception as exc:
                print(f"[sync] Warning: link sync failed: {exc}", file=sys.stderr)
                break
            for link in res.get("links", []):
                file_id = link.get("id")
                url = link.get("url")
                if file_id and url:
                    rowcount = self._conn.execute(
                        "UPDATE metadata SET url = ? WHERE id = ?", (url, file_id)
                    ).rowcount
                    count += rowcount
            if res.get("has_more") and res.get("cursor"):
                cursor = res["cursor"]
            else:
                break
        self._conn.commit()
        return count

    # ── Entry Conversion ─────────────────────────────────────────

    def _entry_to_cached(self, entry: dict[str, Any]) -> CachedMetadata | None:
        """Convert a Dropbox API entry dict to a CachedMetadata."""
        tag = entry.get(".tag", "")
        if tag == "deleted":
            return None

        is_dir = tag == "folder"

        name = entry.get("name", "")
        if is_dir:
            item_type = "folder"
        elif name.endswith(".paper"):
            item_type = "paper"
        else:
            item_type = "file"

        path_lower = entry.get("path_lower", "")
        parent_path = None
        if "/" in path_lower and path_lower != "/":
            parent_path = path_lower.rsplit("/", 1)[0] or "/"

        server_modified = None
        if not is_dir and "server_modified" in entry:
            sm = entry["server_modified"]
            if isinstance(sm, str):
                server_modified = sm
            elif isinstance(sm, datetime):
                server_modified = sm.isoformat()

        return CachedMetadata(
            id=entry["id"],
            name=name,
            path_display=entry.get("path_display", ""),
            path_lower=path_lower,
            is_dir=is_dir,
            item_type=item_type,
            parent_path=parent_path,
            size_bytes=entry.get("size") if not is_dir else None,
            server_modified=server_modified,
            rev=entry.get("rev") if not is_dir else None,
            content_hash=entry.get("content_hash") if not is_dir else None,
        )

    def _upsert_metadata(self, cached: CachedMetadata) -> None:
        """Insert or replace a metadata entry, preserving any cached URL."""
        self._conn.execute(
            """INSERT INTO metadata
            (id, name, path_display, path_lower, is_dir, item_type, parent_path,
             size_bytes, server_modified, rev, content_hash, url, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, (SELECT url FROM metadata WHERE id = ?)), ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, path_display=excluded.path_display,
                path_lower=excluded.path_lower, is_dir=excluded.is_dir,
                item_type=excluded.item_type, parent_path=excluded.parent_path,
                size_bytes=excluded.size_bytes, server_modified=excluded.server_modified,
                rev=excluded.rev, content_hash=excluded.content_hash,
                url=COALESCE(excluded.url, metadata.url),
                synced_at=excluded.synced_at""",
            (
                cached.id,
                cached.name,
                cached.path_display,
                cached.path_lower,
                1 if cached.is_dir else 0,
                cached.item_type,
                cached.parent_path,
                cached.size_bytes,
                cached.server_modified,
                cached.rev,
                cached.content_hash,
                cached.url,
                cached.id,
                cached.synced_at,
            ),
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
