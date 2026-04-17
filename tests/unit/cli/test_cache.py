"""Tests for cache CLI commands: sync and search."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from dropbox_paper_cli.app import app
from dropbox_paper_cli.db.schema import initialize_schema
from dropbox_paper_cli.models.cache import SyncResult


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_cache_db(tmp_path):
    """Provide a mock CacheDatabase that uses an in-memory connection."""
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)

    class FakeDB:
        def __init__(self):
            self._conn = conn

        @property
        def conn(self):
            return self._conn

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def close(self):
            pass

    return FakeDB()


@pytest.fixture
def mock_cache_service():
    """Patch both CacheDatabase and _get_cache_service for CLI tests."""
    with (
        patch("dropbox_paper_cli.cli.cache.CacheDatabase") as mock_db_cls,
        patch("dropbox_paper_cli.cli.cache._get_cache_service") as mock_get_svc,
    ):
        # Set up a mock DB context manager
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        svc = MagicMock()
        mock_get_svc.return_value = svc
        yield svc


class TestCacheSync:
    """paper cache sync [--full]"""

    def test_sync_success(self, runner, mock_cache_service):
        mock_cache_service.sync.return_value = SyncResult(
            added=42,
            updated=15,
            removed=3,
            total=1247,
            duration_seconds=3.2,
            sync_type="incremental",
        )

        result = runner.invoke(app, ["cache", "sync"])
        assert result.exit_code == 0
        assert "42" in result.stdout
        assert "Sync complete" in result.stdout

    def test_sync_full_flag(self, runner, mock_cache_service):
        mock_cache_service.sync.return_value = SyncResult(
            added=100, updated=0, removed=0, total=100, duration_seconds=5.0, sync_type="full"
        )

        result = runner.invoke(app, ["cache", "sync", "--full"])
        assert result.exit_code == 0
        call_kwargs = mock_cache_service.sync.call_args[1]
        assert call_kwargs["force_full"] is True
        assert call_kwargs["concurrency"] == 20

    def test_sync_json_output(self, runner, mock_cache_service):
        mock_cache_service.sync.return_value = SyncResult(
            added=10, updated=5, removed=2, total=100, duration_seconds=1.5, sync_type="full"
        )

        result = runner.invoke(app, ["--json", "cache", "sync"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "synced"
        assert data["added"] == 10
        assert data["total"] == 100
        assert data["sync_type"] == "full"


class TestCacheSearch:
    """paper cache search <QUERY> [--type] [--limit]"""

    def test_search_results(self, runner):
        """Integration test using real SQLite with FTS5."""
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)

        # Populate test data
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0)"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:2', 'TODO.paper', '/TODO.paper', '/todo.paper', 0)"""
        )
        conn.commit()

        with (
            patch("dropbox_paper_cli.cli.cache.CacheDatabase") as mock_db_cls,
        ):
            mock_db = MagicMock()
            mock_db.conn = conn
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            result = runner.invoke(app, ["cache", "search", "Meeting"])
            assert result.exit_code == 0
            assert "Meeting Notes.paper" in result.stdout

        conn.close()

    def test_search_json_output(self, runner):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)

        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0)"""
        )
        conn.commit()

        with (
            patch("dropbox_paper_cli.cli.cache.CacheDatabase") as mock_db_cls,
        ):
            mock_db = MagicMock()
            mock_db.conn = conn
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            result = runner.invoke(app, ["--json", "cache", "search", "Meeting"])
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["query"] == "Meeting"
            assert data["count"] == 1
            assert data["results"][0]["name"] == "Meeting Notes.paper"

        conn.close()

    def test_search_type_filter(self, runner):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)

        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0)"""
        )
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:2', 'Meeting Recordings', '/Meeting Recordings', '/meeting recordings', 1)"""
        )
        conn.commit()

        with (
            patch("dropbox_paper_cli.cli.cache.CacheDatabase") as mock_db_cls,
        ):
            mock_db = MagicMock()
            mock_db.conn = conn
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            result = runner.invoke(app, ["cache", "search", "Meeting", "--type", "file"])
            assert result.exit_code == 0
            assert "Meeting Notes.paper" in result.stdout
            assert "Meeting Recordings" not in result.stdout

        conn.close()

    def test_search_limit(self, runner):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)

        for i in range(10):
            conn.execute(
                """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
                VALUES (?, ?, ?, ?, 0)""",
                (f"id:{i}", f"notes_{i}.paper", f"/notes_{i}.paper", f"/notes_{i}.paper"),
            )
        conn.commit()

        with (
            patch("dropbox_paper_cli.cli.cache.CacheDatabase") as mock_db_cls,
        ):
            mock_db = MagicMock()
            mock_db.conn = conn
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            result = runner.invoke(app, ["--json", "cache", "search", "notes", "--limit", "3"])
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["count"] == 3

        conn.close()

    def test_search_empty_results(self, runner):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)

        with (
            patch("dropbox_paper_cli.cli.cache.CacheDatabase") as mock_db_cls,
        ):
            mock_db = MagicMock()
            mock_db.conn = conn
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            result = runner.invoke(app, ["cache", "search", "nonexistent"])
            assert result.exit_code == 0
            assert "No results" in result.stdout

        conn.close()
