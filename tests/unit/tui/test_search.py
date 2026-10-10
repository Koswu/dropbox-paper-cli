"""Tests for the interactive search TUI."""

from __future__ import annotations

import sqlite3

import pytest

from dropbox_paper_cli.db.schema import initialize_schema
from dropbox_paper_cli.tui.search import SearchApp


def _make_test_db(tmp_path) -> sqlite3.Connection:
    """Create an in-memory SQLite DB with schema and sample data."""
    db_path = tmp_path / "test_cache.db"
    conn = sqlite3.connect(str(db_path))
    initialize_schema(conn)

    conn.execute(
        """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
        VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0, 'paper')"""
    )
    conn.execute(
        """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
        VALUES ('id:2', 'Project Plan.paper', '/Project Plan.paper', '/project plan.paper', 0, 'paper')"""
    )
    conn.execute(
        """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
        VALUES ('id:3', 'Documents', '/Documents', '/documents', 1, 'folder')"""
    )
    conn.commit()
    return conn


class TestSearchApp:
    """Unit tests for SearchApp."""

    def test_app_initializes(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        initialize_schema(conn)
        conn.close()

        app = SearchApp(db_path=db_path, initial_query="test")
        assert app._initial_query == "test"
        assert app._db_path == db_path

    def test_app_with_empty_query(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        initialize_schema(conn)
        conn.close()

        app = SearchApp(db_path=db_path)
        assert app._initial_query == ""
        assert app._results == []

    @pytest.mark.asyncio
    async def test_search_app_compose(self, tmp_path):
        """Verify the app composes without errors."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        initialize_schema(conn)
        conn.close()

        app = SearchApp(db_path=db_path, initial_query="")
        async with app.run_test() as _pilot:
            # Verify widgets exist
            assert app.query_one("#search-input") is not None
            assert app.query_one("#results-table") is not None
            assert app.query_one("#status-bar") is not None

    @pytest.mark.asyncio
    async def test_search_finds_results(self, tmp_path):
        """Verify search populates the table."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        initialize_schema(conn)
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir, item_type)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0, 'paper')"""
        )
        conn.commit()
        conn.close()

        app = SearchApp(db_path=db_path, initial_query="Meeting")
        async with app.run_test() as pilot:
            # Wait for the debounced search to complete
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            # Check results are populated
            from textual.widgets import DataTable

            table = app.query_one("#results-table", DataTable)
            assert table.row_count >= 1

    @pytest.mark.asyncio
    async def test_search_empty_clears_table(self, tmp_path):
        """Verify empty search clears the table."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        initialize_schema(conn)
        conn.close()

        app = SearchApp(db_path=db_path, initial_query="")
        async with app.run_test() as _pilot:
            from textual.widgets import DataTable

            table = app.query_one("#results-table", DataTable)
            assert table.row_count == 0

    @pytest.mark.asyncio
    async def test_quit_binding(self, tmp_path):
        """Verify Escape quits the app."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        initialize_schema(conn)
        conn.close()

        app = SearchApp(db_path=db_path, initial_query="")
        async with app.run_test() as pilot:
            await pilot.press("escape")


class TestClipboard:
    """_try_copy picks a clipboard backend that works on the host terminal."""

    def test_uses_pbcopy_on_macos(self, tmp_path, monkeypatch):
        from dropbox_paper_cli.tui import search

        calls = []
        monkeypatch.setattr(search.sys, "platform", "darwin")
        monkeypatch.setattr(search.shutil, "which", lambda name: "/usr/bin/pbcopy")
        monkeypatch.setattr(search.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
        app = SearchApp(db_path=tmp_path / "test.db")
        monkeypatch.setattr(app, "copy_to_clipboard", lambda text: pytest.fail("used OSC 52"))
        monkeypatch.setattr(app, "notify", lambda *a, **kw: None)

        app._try_copy("https://example.com/链接")

        assert calls[0][0] == (["/usr/bin/pbcopy"],)
        assert calls[0][1]["input"] == "https://example.com/链接".encode()

    def test_uses_osc52_elsewhere(self, tmp_path, monkeypatch):
        from dropbox_paper_cli.tui import search

        copied = []
        monkeypatch.setattr(search.sys, "platform", "linux")
        app = SearchApp(db_path=tmp_path / "test.db")
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
        monkeypatch.setattr(app, "notify", lambda *a, **kw: None)

        app._try_copy("https://example.com")

        assert copied == ["https://example.com"]

    def test_pbcopy_failure_falls_back_to_notification(self, tmp_path, monkeypatch):
        from dropbox_paper_cli.tui import search

        def boom(*a, **kw):
            raise OSError("pbcopy missing")

        notes = []
        monkeypatch.setattr(search.sys, "platform", "darwin")
        monkeypatch.setattr(search.shutil, "which", lambda name: "/usr/bin/pbcopy")
        monkeypatch.setattr(search.subprocess, "run", boom)
        app = SearchApp(db_path=tmp_path / "test.db")
        monkeypatch.setattr(app, "notify", lambda msg, **kw: notes.append(msg))

        app._try_copy("https://example.com")

        assert notes == ["🔗 https://example.com"]


class TestMouseSupport:
    def test_disabled_in_apple_terminal(self, monkeypatch):
        from dropbox_paper_cli.tui.search import _mouse_supported

        monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
        assert _mouse_supported() is False

    def test_enabled_elsewhere(self, monkeypatch):
        from dropbox_paper_cli.tui.search import _mouse_supported

        monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
        assert _mouse_supported() is True
