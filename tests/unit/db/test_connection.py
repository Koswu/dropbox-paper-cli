"""Tests for CacheDatabase: context manager, WAL mode, corruption recovery."""

from __future__ import annotations

import pytest

from dropbox_paper_cli.db.connection import CacheDatabase


@pytest.fixture
def tmp_db_path(tmp_path):
    """Provide a temporary DB path."""
    return tmp_path / "test_cache.db"


class TestCacheDatabaseContextManager:
    """CacheDatabase as a context manager."""

    def test_opens_and_closes(self, tmp_db_path):
        with CacheDatabase(db_path=tmp_db_path) as db:
            assert db.conn is not None
            # Verify we can execute queries
            db.conn.execute("SELECT 1")

    def test_connection_closed_after_exit(self, tmp_db_path):
        db = CacheDatabase(db_path=tmp_db_path)
        with db:
            pass
        # After exit, accessing conn should raise
        with pytest.raises(RuntimeError):
            _ = db.conn

    def test_creates_parent_directory(self, tmp_path):
        db_path = tmp_path / "subdir" / "cache.db"
        with CacheDatabase(db_path=db_path) as db:
            db.conn.execute("SELECT 1")
        assert db_path.exists()


class TestWALMode:
    """WAL mode activation."""

    def test_wal_mode_enabled(self, tmp_db_path):
        with CacheDatabase(db_path=tmp_db_path) as db:
            result = db.conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0] == "wal"


class TestCorruptionRecovery:
    """Corruption recovery: delete and recreate on DatabaseError."""

    def test_recovers_from_corrupt_db(self, tmp_db_path):
        # Create a corrupt database file
        tmp_db_path.write_bytes(b"this is not a valid sqlite database")

        # Should recover by deleting and recreating
        with CacheDatabase(db_path=tmp_db_path) as db:
            # Should be able to use the database
            db.conn.execute("SELECT 1")
            # Schema should be initialized
            tables = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = {t[0] for t in tables}
            assert "metadata" in table_names
            assert "sync_state" in table_names


class TestSchemaInitialization:
    """Schema is initialized on connection."""

    def test_metadata_table_exists(self, tmp_db_path):
        with CacheDatabase(db_path=tmp_db_path) as db:
            tables = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = {t[0] for t in tables}
            assert "metadata" in table_names

    def test_sync_state_table_exists(self, tmp_db_path):
        with CacheDatabase(db_path=tmp_db_path) as db:
            tables = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = {t[0] for t in tables}
            assert "sync_state" in table_names

    def test_fts_table_exists(self, tmp_db_path):
        with CacheDatabase(db_path=tmp_db_path) as db:
            tables = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = {t[0] for t in tables}
            assert "metadata_fts" in table_names
