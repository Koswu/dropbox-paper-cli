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
