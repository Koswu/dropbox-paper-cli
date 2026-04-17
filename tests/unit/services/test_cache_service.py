"""Tests for cache_service: parallel full sync, incremental sync, search via FTS5."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import dropbox.files
import pytest

from dropbox_paper_cli.db.schema import initialize_schema
from dropbox_paper_cli.services.cache_service import CacheService


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema initialized."""
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def mock_client():
    """Mock Dropbox client."""
    return MagicMock()


def _make_list_result(entries, cursor="cursor1", has_more=False):
    """Create a mock files_list_folder / files_list_folder_continue result."""
    r = MagicMock()
    r.entries = entries
    r.cursor = cursor
    r.has_more = has_more
    return r


def _make_file_entry(
    id="id:file1", name="test.paper", path_display="/test.paper", path_lower="/test.paper"
):
    entry = MagicMock(spec=dropbox.files.FileMetadata)
    entry.id = id
    entry.name = name
    entry.path_display = path_display
    entry.path_lower = path_lower
    entry.size = 1024
    entry.server_modified = "2025-07-18T09:00:00"
    entry.rev = "015abc"
    entry.content_hash = "hash123"
    return entry


def _make_folder_entry(
    id="id:folder1", name="Project", path_display="/Project", path_lower="/project"
):
    entry = MagicMock(spec=dropbox.files.FolderMetadata)
    entry.id = id
    entry.name = name
    entry.path_display = path_display
    entry.path_lower = path_lower
    return entry


def _make_deleted_entry(path_lower="/deleted.paper"):
    entry = MagicMock(spec=dropbox.files.DeletedMetadata)
    entry.path_lower = path_lower
    return entry


class TestFullSyncNoSubfolders:
    """Full sync with only files at top level — no threading involved."""

    def test_adds_file_items(self, conn, mock_client):
        mock_client.files_list_folder.return_value = _make_list_result(
            [
                _make_file_entry(),
                _make_file_entry(
                    id="id:file2",
                    name="f2.paper",
                    path_display="/f2.paper",
                    path_lower="/f2.paper",
                ),
            ],
            cursor="c1",
        )
        svc = CacheService(conn=conn, client=mock_client)
        result = svc.sync()
        assert result.added == 2
        assert result.total == 2
        assert result.sync_type == "full"

    def test_updates_existing(self, conn, mock_client):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:file1', 'old_name.paper', '/test.paper', '/test.paper', 0)"""
        )
        conn.commit()

        mock_client.files_list_folder.return_value = _make_list_result(
            [_make_file_entry()], cursor="c1"
        )
        svc = CacheService(conn=conn, client=mock_client)
        result = svc.sync()
        assert result.updated == 1
        assert result.added == 0

    def test_removes_deleted(self, conn, mock_client):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:gone', 'gone.paper', '/gone.paper', '/gone.paper', 0)"""
        )
        conn.commit()

        mock_client.files_list_folder.return_value = _make_list_result(
            [_make_file_entry()], cursor="c1"
        )
        svc = CacheService(conn=conn, client=mock_client)
        result = svc.sync()
        assert result.removed == 1

    def test_saves_sync_state(self, conn, mock_client):
        mock_client.files_list_folder.return_value = _make_list_result([], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        svc.sync()

        row = conn.execute("SELECT cursor FROM sync_state WHERE key = 'default'").fetchone()
        # New-style sync saves None for default cursor (per-folder cursors used instead)
        assert row is not None

    def test_path_normalization(self, conn, mock_client):
        """'/' is normalized to '' for team root."""
        mock_client.files_list_folder.return_value = _make_list_result([], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        svc.sync(path="/")

        mock_client.files_list_folder.assert_called_once_with("", recursive=False, limit=2000)


class TestFullSyncWithSubfolders:
    """Full sync that discovers subfolders and uses parallel workers."""

    def test_adds_folder_and_children(self, conn, mock_client):
        folder = _make_folder_entry()
        root_file = _make_file_entry()
        child_file = _make_file_entry(
            id="id:child1",
            name="child.paper",
            path_display="/Project/child.paper",
            path_lower="/project/child.paper",
        )

        # Top-level listing (non-recursive)
        mock_client.files_list_folder.return_value = _make_list_result(
            [root_file, folder], cursor="top_cursor"
        )

        # Worker client for the subfolder
        worker_mock = MagicMock()
        worker_mock.files_list_folder.return_value = _make_list_result(
            [child_file], cursor="folder_cursor"
        )

        svc = CacheService(
            conn=conn, client=mock_client, client_factory=lambda: worker_mock
        )
        result = svc.sync(concurrency=1)

        # root_file + folder from top-level + child from worker
        assert result.added == 3
        assert result.total == 3
        assert result.sync_type == "full"

    def test_saves_per_folder_cursors(self, conn, mock_client):
        folder = _make_folder_entry()
        mock_client.files_list_folder.return_value = _make_list_result(
            [folder], cursor="top"
        )

        worker_mock = MagicMock()
        worker_mock.files_list_folder.return_value = _make_list_result(
            [], cursor="folder_cursor_saved"
        )

        svc = CacheService(
            conn=conn, client=mock_client, client_factory=lambda: worker_mock
        )
        svc.sync(concurrency=1)

        row = conn.execute(
            "SELECT cursor FROM sync_state WHERE key = 'cursor:id:folder1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "folder_cursor_saved"


class TestIncrementalSync:
    """Incremental sync uses saved per-folder cursors."""

    def test_uses_folder_cursors(self, conn, mock_client):
        # Set up per-folder cursor (new style)
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:folder1', 'old_folder_cursor', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', NULL, '2025-01-01T00:00:00Z', 0)"""
        )
        conn.commit()

        folder = _make_folder_entry()
        new_file = _make_file_entry()

        # Top-level listing
        mock_client.files_list_folder.return_value = _make_list_result(
            [new_file, folder], cursor="top_new"
        )

        # Worker continues folder cursor
        worker_mock = MagicMock()
        worker_mock.files_list_folder_continue.return_value = _make_list_result(
            [
                _make_file_entry(
                    id="id:inc1",
                    name="inc.paper",
                    path_display="/Project/inc.paper",
                    path_lower="/project/inc.paper",
                )
            ],
            cursor="new_folder_cursor",
        )

        svc = CacheService(
            conn=conn, client=mock_client, client_factory=lambda: worker_mock
        )
        result = svc.sync(concurrency=1)

        assert result.sync_type == "incremental"
        assert result.added >= 1
        worker_mock.files_list_folder_continue.assert_called_once_with("old_folder_cursor")

    def test_incremental_handles_deletes(self, conn, mock_client):
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:folder1', 'cursor1', '2025-01-01T00:00:00Z', 1)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', NULL, '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:del', 'deleted.paper', '/project/deleted.paper', '/project/deleted.paper', 0)"""
        )
        conn.commit()

        folder = _make_folder_entry()
        deleted = _make_deleted_entry(path_lower="/project/deleted.paper")

        mock_client.files_list_folder.return_value = _make_list_result(
            [folder], cursor="top"
        )

        worker_mock = MagicMock()
        worker_mock.files_list_folder_continue.return_value = _make_list_result(
            [deleted], cursor="cursor2"
        )

        svc = CacheService(
            conn=conn, client=mock_client, client_factory=lambda: worker_mock
        )
        result = svc.sync(concurrency=1)
        assert result.removed >= 1

    def test_legacy_single_cursor_forces_full(self, conn, mock_client):
        """Old-style single cursor triggers full resync, not incremental."""
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', 'old_single_cursor', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.commit()

        mock_client.files_list_folder.return_value = _make_list_result([], cursor="new")
        svc = CacheService(conn=conn, client=mock_client)
        result = svc.sync()
        assert result.sync_type == "full"
        mock_client.files_list_folder.assert_called_once()

    def test_force_full_ignores_cursors(self, conn, mock_client):
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:folder1', 'saved_cursor', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.commit()

        mock_client.files_list_folder.return_value = _make_list_result([], cursor="fresh")
        svc = CacheService(conn=conn, client=mock_client)
        result = svc.sync(force_full=True)
        assert result.sync_type == "full"
        mock_client.files_list_folder.assert_called_once()


class TestSyncRoot:
    """Sync root change triggers full resync."""

    def test_path_change_forces_full(self, conn, mock_client):
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('meta:sync_root', '/old', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('cursor:id:folder1', 'saved', '2025-01-01T00:00:00Z', 0)"""
        )
        conn.commit()

        mock_client.files_list_folder.return_value = _make_list_result([], cursor="new")
        svc = CacheService(conn=conn, client=mock_client)
        result = svc.sync(path="/new")
        assert result.sync_type == "full"

    def test_sync_root_saved(self, conn, mock_client):
        mock_client.files_list_folder.return_value = _make_list_result([], cursor="c1")
        svc = CacheService(conn=conn, client=mock_client)
        svc.sync(path="/my/path")

        row = conn.execute(
            "SELECT cursor FROM sync_state WHERE key = 'meta:sync_root'"
        ).fetchone()
        assert row[0] == "/my/path"


class TestProgressCallback:
    """Progress callback is invoked during sync."""

    def test_callback_invoked(self, conn, mock_client):
        mock_client.files_list_folder.return_value = _make_list_result(
            [_make_file_entry()], cursor="c1"
        )
        calls = []
        svc = CacheService(conn=conn, client=mock_client)
        svc.sync(on_progress=lambda r: calls.append(r.added + r.updated))
        assert len(calls) >= 1


class TestSearch:
    """FTS5 keyword search with type filter and limit."""

    @pytest.fixture
    def cache_service(self, conn, mock_client):
        return CacheService(conn=conn, client=mock_client)

    def test_search_by_name(self, cache_service, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0)"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:2', 'TODO.paper', '/TODO.paper', '/todo.paper', 0)"""
        )
        conn.commit()

        results = cache_service.search("Meeting")
        assert len(results) == 1
        assert results[0].name == "Meeting Notes.paper"

    def test_search_type_filter_file(self, cache_service, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0, 'paper')"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:2', 'Meeting Recordings', '/Meeting Recordings', '/meeting recordings', 1, 'folder')"""
        )
        conn.commit()

        results = cache_service.search("Meeting", item_type="paper")
        assert len(results) == 1
        assert results[0].item_type == "paper"

    def test_search_type_filter_folder(self, cache_service, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0, 'paper')"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:2', 'Meeting Recordings', '/Meeting Recordings', '/meeting recordings', 1, 'folder')"""
        )
        conn.commit()

        results = cache_service.search("Meeting", item_type="folder")
        assert len(results) == 1
        assert results[0].item_type == "folder"

    def test_search_limit(self, cache_service, conn):
        for i in range(10):
            conn.execute(
                """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
                VALUES (?, ?, ?, ?, 0)""",
                (f"id:{i}", f"notes_{i}.paper", f"/notes_{i}.paper", f"/notes_{i}.paper"),
            )
        conn.commit()

        results = cache_service.search("notes", limit=3)
        assert len(results) == 3

    def test_search_empty_query(self, cache_service, conn):
        results = cache_service.search("")
        assert results == []

    def test_search_no_results(self, cache_service, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'test.paper', '/test.paper', '/test.paper', 0)"""
        )
        conn.commit()

        results = cache_service.search("nonexistent")
        assert results == []
