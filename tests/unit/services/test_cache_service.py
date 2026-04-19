"""Tests for cache_service: async parallel full sync, incremental sync, search via LIKE."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from dropbox_paper_cli.db.schema import initialize_schema
from dropbox_paper_cli.services.cache_service import CacheService, search_cache


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema initialized."""
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def mock_client():
    """Mock DropboxHttpClient with async rpc method."""
    client = AsyncMock()
    client.rpc = AsyncMock()
    # Default to personal account (same namespace IDs → /home/ URL prefix)
    token = MagicMock()
    token.root_namespace_id = "ns:123"
    token.home_namespace_id = "ns:123"
    client._token = token
    return client


# ── Helper factories ─────────────────────────────────────────────


def _make_rpc_response(entries, cursor="cursor1", has_more=False):
    """Create a dict matching Dropbox list_folder / list_folder/continue response."""
    return {"entries": entries, "cursor": cursor, "has_more": has_more}


def _make_file_dict(
    id="id:file1",
    name="test.txt",
    path_display="/test.txt",
    path_lower="/test.txt",
):
    return {
        ".tag": "file",
        "id": id,
        "name": name,
        "path_display": path_display,
        "path_lower": path_lower,
        "size": 1024,
        "server_modified": "2025-07-18T09:00:00",
        "rev": "015abc",
        "content_hash": "hash123",
    }


def _make_folder_dict(
    id="id:folder1",
    name="Project",
    path_display="/Project",
    path_lower="/project",
):
    return {
        ".tag": "folder",
        "id": id,
        "name": name,
        "path_display": path_display,
        "path_lower": path_lower,
    }


def _make_deleted_dict(
    name="deleted.paper",
    path_display="/deleted.paper",
    path_lower="/deleted.paper",
):
    return {
        ".tag": "deleted",
        "name": name,
        "path_display": path_display,
        "path_lower": path_lower,
    }


class TestFullSyncNoSubfolders:
    """Full sync with only files at top level — no subfolders involved."""

    async def test_adds_file_items(self, conn, mock_client):
        mock_client.rpc.return_value = _make_rpc_response(
            [
                _make_file_dict(),
                _make_file_dict(
                    id="id:file2",
                    name="f2.paper",
                    path_display="/f2.paper",
                    path_lower="/f2.paper",
                ),
            ],
            cursor="c1",
        )
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        assert result.added == 2
        assert result.total == 2
        assert result.sync_type == "full"

    async def test_updates_existing(self, conn, mock_client):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:file1', 'old_name.txt', '/test.txt', '/test.txt', 0)"""
        )
        conn.commit()

        mock_client.rpc.return_value = _make_rpc_response([_make_file_dict()], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        assert result.updated == 1
        assert result.added == 0

    async def test_removes_deleted(self, conn, mock_client):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:gone', 'gone.paper', '/gone.paper', '/gone.paper', 0)"""
        )
        conn.commit()

        mock_client.rpc.return_value = _make_rpc_response([_make_file_dict()], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        assert result.removed == 1

    async def test_saves_sync_state(self, conn, mock_client):
        mock_client.rpc.return_value = _make_rpc_response([], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        await svc.sync()

        row = conn.execute("SELECT cursor FROM sync_state WHERE key = 'default'").fetchone()
        assert row is not None

    async def test_path_normalization(self, conn, mock_client):
        """'/' is normalized to '' for team root."""
        mock_client.rpc.return_value = _make_rpc_response([], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        await svc.sync(path="/")

        mock_client.rpc.assert_any_call(
            "files/list_folder",
            {"path": "", "recursive": False, "limit": 2000, "include_non_downloadable_files": True},
        )


class TestFullSyncWithSubfolders:
    """Full sync that expands one level to discover sub-folders for parallelism."""

    async def test_adds_folder_and_children(self, conn, mock_client):
        top_folder = _make_folder_dict(
            id="id:top1", name="Team", path_display="/Team", path_lower="/team"
        )
        root_file = _make_file_dict()
        subfolder = _make_folder_dict(
            id="id:sub1",
            name="Docs",
            path_display="/Team/Docs",
            path_lower="/team/docs",
        )
        child_file = _make_file_dict(
            id="id:child1",
            name="child.paper",
            path_display="/Team/Docs/child.paper",
            path_lower="/team/docs/child.paper",
        )

        def rpc_router(endpoint, body):
            if endpoint == "files/list_folder" and not body.get("recursive"):
                path = body.get("path", "")
                if path == "":
                    return _make_rpc_response([root_file, top_folder], cursor="root_c")
                if path == "/team":
                    return _make_rpc_response([subfolder], cursor="expand_c")
                return _make_rpc_response([])
            if endpoint == "files/list_folder" and body.get("recursive"):
                return _make_rpc_response([child_file], cursor="sub_cursor")
            return _make_rpc_response([])

        mock_client.rpc = AsyncMock(side_effect=rpc_router)
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync(concurrency=1)

        # root_file + top_folder (step 1) + subfolder (step 2) + child_file (step 3)
        assert result.added == 4
        assert result.total == 4
        assert result.sync_type == "full"

    async def test_no_subfolders_skips_recursive(self, conn, mock_client):
        """Top folder with only files — no recursive tasks needed."""
        top_folder = _make_folder_dict(
            id="id:top1", name="Team", path_display="/Team", path_lower="/team"
        )
        child_file = _make_file_dict(
            id="id:child1",
            name="child.paper",
            path_display="/Team/child.paper",
            path_lower="/team/child.paper",
        )

        def rpc_router(endpoint, body):
            if endpoint == "files/list_folder" and not body.get("recursive"):
                path = body.get("path", "")
                if path == "":
                    return _make_rpc_response([top_folder], cursor="root_c")
                if path == "/team":
                    return _make_rpc_response([child_file], cursor="expand_c")
                return _make_rpc_response([])
            if endpoint == "files/list_folder" and body.get("recursive"):
                raise AssertionError("Should not call recursive listing without sub-folders")
            return _make_rpc_response([])

        mock_client.rpc = AsyncMock(side_effect=rpc_router)
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync(concurrency=1)

        assert result.added == 2  # top_folder + child_file from expansion
        assert result.total == 2

    async def test_saves_per_subfolder_cursors(self, conn, mock_client):
        top_folder = _make_folder_dict(
            id="id:top1", name="Team", path_display="/Team", path_lower="/team"
        )
        subfolder = _make_folder_dict(
            id="id:sub1",
            name="Docs",
            path_display="/Team/Docs",
            path_lower="/team/docs",
        )

        def rpc_router(endpoint, body):
            if endpoint == "files/list_folder" and not body.get("recursive"):
                path = body.get("path", "")
                if path == "":
                    return _make_rpc_response([top_folder], cursor="root_c")
                if path == "/team":
                    return _make_rpc_response([subfolder], cursor="expand_c")
                return _make_rpc_response([])
            if endpoint == "files/list_folder" and body.get("recursive"):
                return _make_rpc_response([], cursor="sub_cursor_saved")
            return _make_rpc_response([])

        mock_client.rpc = AsyncMock(side_effect=rpc_router)
        svc = CacheService(conn=conn, client=mock_client)
        await svc.sync(concurrency=1)

        # Cursor saved for sub-folder (not top-level folder)
        row = conn.execute("SELECT cursor FROM sync_state WHERE key = 'cursor:id:sub1'").fetchone()
        assert row is not None
        assert row[0] == "sub_cursor_saved"

        # cursor_format=v2 saved
        fmt = conn.execute(
            "SELECT cursor FROM sync_state WHERE key = 'meta:cursor_format'"
        ).fetchone()
        assert fmt is not None
        assert fmt[0] == "v2"


class TestIncrementalSync:
    """Incremental sync uses saved per-subfolder cursors (v2 format)."""

    def _setup_v2_state(self, conn):
        """Insert v2 cursor format and sub-folder cursor with metadata."""
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('meta:cursor_format', 'v2', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:sub1', 'old_sub_cursor', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', NULL, '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, parent_path)
            VALUES ('id:top1', 'Team', '/Team', '/team', 1, '')"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, parent_path)
            VALUES ('id:sub1', 'Docs', '/Team/Docs', '/team/docs', 1, '/team')"""
        )
        conn.commit()

    def _make_v2_router(self, extra_entries=None):
        """Router that handles two-level expansion for incremental sync."""
        top_folder = _make_folder_dict(
            id="id:top1", name="Team", path_display="/Team", path_lower="/team"
        )
        subfolder = _make_folder_dict(
            id="id:sub1", name="Docs", path_display="/Team/Docs", path_lower="/team/docs"
        )
        continue_entries = extra_entries or []

        def rpc_router(endpoint, body):
            if endpoint == "files/list_folder":
                path = body.get("path", "")
                if path == "":
                    return _make_rpc_response([top_folder], cursor="root_c")
                if path == "/team":
                    return _make_rpc_response([subfolder], cursor="expand_c")
                return _make_rpc_response([])
            if endpoint == "files/list_folder/continue":
                return _make_rpc_response(continue_entries, cursor="new_sub_cursor")
            return _make_rpc_response([])

        return rpc_router

    async def test_uses_folder_cursors(self, conn, mock_client):
        self._setup_v2_state(conn)
        inc_file = _make_file_dict(
            id="id:inc1",
            name="inc.paper",
            path_display="/Team/Docs/inc.paper",
            path_lower="/team/docs/inc.paper",
        )
        mock_client.rpc = AsyncMock(side_effect=self._make_v2_router([inc_file]))
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync(concurrency=1)

        assert result.sync_type == "incremental"
        assert result.added >= 1

        # Verify the continue call used the saved sub-folder cursor
        continue_calls = [
            c for c in mock_client.rpc.call_args_list if c.args[0] == "files/list_folder/continue"
        ]
        assert len(continue_calls) == 1
        assert continue_calls[0].args[1]["cursor"] == "old_sub_cursor"

    async def test_incremental_handles_deletes(self, conn, mock_client):
        self._setup_v2_state(conn)
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:del', 'deleted.paper', '/team/docs/deleted.paper',
                    '/team/docs/deleted.paper', 0)"""
        )
        conn.commit()

        deleted = _make_deleted_dict(
            name="deleted.paper",
            path_display="/team/docs/deleted.paper",
            path_lower="/team/docs/deleted.paper",
        )
        mock_client.rpc = AsyncMock(side_effect=self._make_v2_router([deleted]))
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync(concurrency=1)
        assert result.removed >= 1

    async def test_legacy_single_cursor_forces_full(self, conn, mock_client):
        """Old-style single cursor triggers full resync, not incremental."""
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', 'old_single_cursor', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.commit()

        mock_client.rpc.return_value = _make_rpc_response([], cursor="new")
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        assert result.sync_type == "full"
        # list_folder + sharing/list_shared_links
        assert mock_client.rpc.call_count == 2

    async def test_v1_cursors_without_format_forces_full(self, conn, mock_client):
        """Old per-folder cursors without cursor_format=v2 trigger full sync."""
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:folder1', 'saved_cursor', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', NULL, '2025-01-01T00:00:00Z', 0)"""
        )
        conn.commit()

        mock_client.rpc.return_value = _make_rpc_response([], cursor="new")
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        assert result.sync_type == "full"

    async def test_force_full_ignores_cursors(self, conn, mock_client):
        self._setup_v2_state(conn)

        mock_client.rpc.return_value = _make_rpc_response([], cursor="fresh")
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync(force_full=True)
        assert result.sync_type == "full"


class TestSyncRoot:
    """Sync root change triggers full resync."""

    async def test_path_change_forces_full(self, conn, mock_client):
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('meta:sync_root', '/old', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:folder1', 'saved', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.commit()

        mock_client.rpc.return_value = _make_rpc_response([], cursor="new")
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync(path="/new")
        assert result.sync_type == "full"

    async def test_sync_root_saved(self, conn, mock_client):
        mock_client.rpc.return_value = _make_rpc_response([], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        await svc.sync(path="/my/path")

        row = conn.execute("SELECT cursor FROM sync_state WHERE key = 'meta:sync_root'").fetchone()
        assert row[0] == "/my/path"


class TestProgressCallback:
    """Progress callback is invoked during sync."""

    async def test_callback_invoked(self, conn, mock_client):
        mock_client.rpc.return_value = _make_rpc_response([_make_file_dict()], cursor="c1")
        calls = []
        svc = CacheService(conn=conn, client=mock_client)
        await svc.sync(on_progress=lambda r: calls.append(r.added + r.updated))
        assert len(calls) >= 1


class TestSearch:
    """LIKE-based keyword search with type filter and limit."""

    def test_search_by_name(self, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0)"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:2', 'TODO.paper', '/TODO.paper', '/todo.paper', 0)"""
        )
        conn.commit()

        results = search_cache(conn, "Meeting")
        assert len(results) == 1
        assert results[0].name == "Meeting Notes.paper"

    def test_search_type_filter_file(self, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0, 'paper')"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:2', 'Meeting Recordings', '/Meeting Recordings', '/meeting recordings', 1, 'folder')"""
        )
        conn.commit()

        results = search_cache(conn, "Meeting", item_type="paper")
        assert len(results) == 1
        assert results[0].item_type == "paper"

    def test_search_type_filter_folder(self, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0, 'paper')"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:2', 'Meeting Recordings', '/Meeting Recordings', '/meeting recordings', 1, 'folder')"""
        )
        conn.commit()

        results = search_cache(conn, "Meeting", item_type="folder")
        assert len(results) == 1
        assert results[0].item_type == "folder"

    def test_search_limit(self, conn):
        for i in range(10):
            conn.execute(
                """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
                VALUES (?, ?, ?, ?, 0)""",
                (f"id:{i}", f"notes_{i}.paper", f"/notes_{i}.paper", f"/notes_{i}.paper"),
            )
        conn.commit()

        results = search_cache(conn, "notes", limit=3)
        assert len(results) == 3

    def test_search_empty_query(self, conn):
        results = search_cache(conn, "")
        assert results == []

    def test_search_no_results(self, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'test.paper', '/test.paper', '/test.paper', 0)"""
        )
        conn.commit()

        results = search_cache(conn, "nonexistent")
        assert results == []


class TestLinkSync:
    """Shared link sync during full sync."""

    async def test_full_sync_caches_links(self, conn, mock_client):
        """Full sync fetches shared links and stores URLs by file ID."""
        file_entry = _make_file_dict(id="id:f1", name="a.paper")
        list_folder_resp = _make_rpc_response([file_entry], cursor="c1")
        link_resp = {
            "links": [{"id": "id:f1", "url": "https://dbx.link/a"}],
            "has_more": False,
        }

        async def rpc_router(endpoint, params=None):
            if endpoint == "sharing/get_file_metadata/batch":
                return [
                    {
                        "file": "id:f1",
                        "result": {
                            ".tag": "metadata",
                            "id": "id:f1",
                            "preview_url": "https://dbx.preview/a",
                        },
                    }
                ]
            if endpoint == "sharing/list_shared_links":
                return link_resp
            return list_folder_resp

        mock_client.rpc = AsyncMock(side_effect=rpc_router)
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        # 1 preview URL + 1 sharing link (sharing link overwrites preview)
        assert result.links_cached >= 1

        row = conn.execute("SELECT url FROM metadata WHERE id = 'id:f1'").fetchone()
        assert row[0] == "https://dbx.link/a"

    async def test_incremental_sync_skips_link_sync(self, conn, mock_client):
        """Incremental sync does not run link sync phase."""
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('meta:cursor_format', 'v2', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:sub1', 'saved_cursor', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', NULL, '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, parent_path)
            VALUES ('id:top1', 'Team', '/Team', '/team', 1, '')"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, parent_path)
            VALUES ('id:sub1', 'Docs', '/Team/Docs', '/team/docs', 1, '/team')"""
        )
        conn.commit()

        top_folder = _make_folder_dict(
            id="id:top1", name="Team", path_display="/Team", path_lower="/team"
        )
        subfolder = _make_folder_dict(
            id="id:sub1", name="Docs", path_display="/Team/Docs", path_lower="/team/docs"
        )

        async def rpc_router(endpoint, params=None):
            if endpoint == "sharing/list_shared_links":
                raise AssertionError("Should not call sharing API on incremental sync")
            if endpoint == "files/list_folder":
                path = params.get("path", "") if params else ""
                if path == "":
                    return _make_rpc_response([top_folder], cursor="root_c")
                if path == "/team":
                    return _make_rpc_response([subfolder], cursor="expand_c")
                return _make_rpc_response([])
            if endpoint == "files/list_folder/continue":
                return _make_rpc_response([], cursor="new_cursor")
            return _make_rpc_response([])

        mock_client.rpc = AsyncMock(side_effect=rpc_router)
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        assert result.sync_type == "incremental"
        assert result.links_cached == 0

    async def test_upsert_preserves_existing_url(self, conn, mock_client):
        """Metadata upsert does not overwrite a cached URL with NULL."""
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, url)
            VALUES ('id:f1', 'a.txt', '/a.txt', '/a.txt', 0, 'https://dbx.link/a')"""
        )
        conn.commit()

        file_entry = _make_file_dict(
            id="id:f1", name="a.txt", path_display="/a.txt", path_lower="/a.txt"
        )
        empty_resp = _make_rpc_response([file_entry], cursor="c1")
        link_resp = {"links": [], "has_more": False}

        async def rpc_router(endpoint, params=None):
            if endpoint == "sharing/list_shared_links":
                return link_resp
            return empty_resp

        mock_client.rpc = AsyncMock(side_effect=rpc_router)
        svc = CacheService(conn=conn, client=mock_client)
        await svc.sync(force_full=True)

        # URL is now the constructed web URL (overwrites old sharing link during sync)
        row = conn.execute("SELECT url FROM metadata WHERE id = 'id:f1'").fetchone()
        assert row[0] == "https://www.dropbox.com/home/a.txt"

    async def test_link_sync_pagination(self, conn, mock_client):
        """Link sync handles paginated responses."""
        f1 = _make_file_dict(id="id:f1", name="a.paper")
        f2 = _make_file_dict(
            id="id:f2", name="b.paper", path_display="/b.paper", path_lower="/b.paper"
        )
        list_resp = _make_rpc_response([f1, f2], cursor="c1")

        call_count = [0]

        async def rpc_router(endpoint, params=None):
            if endpoint == "sharing/get_file_metadata/batch":
                return [
                    {
                        "file": fid,
                        "result": {
                            ".tag": "metadata",
                            "id": fid,
                            "preview_url": f"https://dbx.preview/{fid}",
                        },
                    }
                    for fid in (params or {}).get("files", [])
                ]
            if endpoint == "sharing/list_shared_links":
                call_count[0] += 1
                if call_count[0] == 1:
                    return {
                        "links": [{"id": "id:f1", "url": "https://dbx.link/a"}],
                        "has_more": True,
                        "cursor": "link_cursor",
                    }
                return {
                    "links": [{"id": "id:f2", "url": "https://dbx.link/b"}],
                    "has_more": False,
                }
            return list_resp

        mock_client.rpc = AsyncMock(side_effect=rpc_router)
        svc = CacheService(conn=conn, client=mock_client)
        result = await svc.sync()
        # 2 preview URLs + 2 sharing link overrides
        assert result.links_cached == 4
