"""Tests for schema DDL: tables, FTS5, triggers, sync_state, schema_version."""

from __future__ import annotations

import sqlite3

import pytest

from dropbox_paper_cli.db.schema import SCHEMA_VERSION, initialize_schema


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema initialized."""
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)
    yield connection
    connection.close()


class TestMetadataTable:
    """metadata table creation and constraints."""

    def test_metadata_table_exists(self, conn):
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'"
        ).fetchall()
        assert len(tables) == 1

    def test_metadata_columns(self, conn):
        info = conn.execute("PRAGMA table_info(metadata)").fetchall()
        col_names = {row[1] for row in info}
        expected = {
            "id",
            "name",
            "path_display",
            "path_lower",
            "is_dir",
            "item_type",
            "parent_path",
            "size_bytes",
            "server_modified",
            "rev",
            "content_hash",
            "synced_at",
        }
        assert expected.issubset(col_names)

    def test_insert_and_query(self, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'test.paper', '/test.paper', '/test.paper', 0)"""
        )
        conn.commit()
        row = conn.execute("SELECT * FROM metadata WHERE id = 'id:1'").fetchone()
        assert row is not None

    def test_unique_path_display(self, conn):
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'test.paper', '/test.paper', '/test.paper', 0)"""
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
                VALUES ('id:2', 'test2.paper', '/test.paper', '/test.paper', 0)"""
            )


class TestIndexes:
    """Index creation."""

    def test_parent_path_index(self, conn):
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_metadata_parent_path'"
        ).fetchall()
        assert len(indexes) == 1

    def test_is_dir_index(self, conn):
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_metadata_is_dir'"
        ).fetchall()
        assert len(indexes) == 1

    def test_item_type_index(self, conn):
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_metadata_item_type'"
        ).fetchall()
        assert len(indexes) == 1

    def test_name_index(self, conn):
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_metadata_name'"
        ).fetchall()
        assert len(indexes) == 1


class TestFTS5:
    """FTS5 virtual table and triggers."""

    def test_fts_table_exists(self, conn):
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata_fts'"
        ).fetchall()
        assert len(tables) == 1

    def test_fts_insert_trigger(self, conn):
        """Inserting into metadata automatically populates FTS."""
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0)"""
        )
        conn.commit()
        results = conn.execute(
            "SELECT * FROM metadata_fts WHERE metadata_fts MATCH 'Meeting'"
        ).fetchall()
        assert len(results) == 1

    def test_fts_delete_trigger(self, conn):
        """Deleting from metadata removes from FTS."""
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Meeting Notes.paper', '/Meeting Notes.paper', '/meeting notes.paper', 0)"""
        )
        conn.commit()
        conn.execute("DELETE FROM metadata WHERE id = 'id:1'")
        conn.commit()
        results = conn.execute(
            "SELECT * FROM metadata_fts WHERE metadata_fts MATCH 'Meeting'"
        ).fetchall()
        assert len(results) == 0

    def test_fts_update_trigger(self, conn):
        """Updating metadata updates FTS."""
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'Old Name.paper', '/Old Name.paper', '/old name.paper', 0)"""
        )
        conn.commit()
        conn.execute(
            """UPDATE metadata SET name = 'New Name.paper', path_display = '/New Name.paper'
            WHERE id = 'id:1'"""
        )
        conn.commit()
        old = conn.execute("SELECT * FROM metadata_fts WHERE metadata_fts MATCH 'Old'").fetchall()
        new = conn.execute("SELECT * FROM metadata_fts WHERE metadata_fts MATCH 'New'").fetchall()
        assert len(old) == 0
        assert len(new) == 1

    def test_fts_search_by_path(self, conn):
        """FTS can search by path_display."""
        conn.execute(
            """INSERT INTO metadata (id, name, path_display, path_lower, is_dir)
            VALUES ('id:1', 'notes.paper', '/Project/notes.paper', '/project/notes.paper', 0)"""
        )
        conn.commit()
        results = conn.execute(
            "SELECT * FROM metadata_fts WHERE metadata_fts MATCH 'Project'"
        ).fetchall()
        assert len(results) == 1


class TestSyncStateTable:
    """sync_state table."""

    def test_sync_state_table_exists(self, conn):
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_state'"
        ).fetchall()
        assert len(tables) == 1

    def test_insert_and_query_sync_state(self, conn):
        conn.execute(
            """INSERT INTO sync_state (key, cursor, last_sync_at, total_items)
            VALUES ('default', 'cursor123', '2025-07-18T00:00:00Z', 42)"""
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sync_state WHERE key = 'default'").fetchone()
        assert row[1] == "cursor123"
        assert row[3] == 42


class TestSchemaVersion:
    """schema_version table."""

    def test_schema_version_recorded(self, conn):
        row = conn.execute(
            "SELECT version FROM schema_version WHERE version = ?", (SCHEMA_VERSION,)
        ).fetchone()
        assert row is not None
        assert row[0] == SCHEMA_VERSION

    def test_initialize_schema_idempotent(self, conn):
        """Calling initialize_schema again doesn't duplicate entries."""
        initialize_schema(conn)
        count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert count == 1


class TestMigrationV1ToV2:
    """Migration from v1 (no item_type) to v2."""

    @pytest.fixture
    def v1_conn(self):
        """Create a v1 schema database with test data."""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """CREATE TABLE metadata (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                path_display TEXT UNIQUE NOT NULL, path_lower TEXT NOT NULL,
                is_dir INTEGER NOT NULL DEFAULT 0, parent_path TEXT,
                size_bytes INTEGER, server_modified TEXT, rev TEXT,
                content_hash TEXT, synced_at TEXT NOT NULL)"""
        )
        conn.execute(
            "CREATE TABLE sync_state (key TEXT PRIMARY KEY, cursor TEXT, "
            "last_sync_at TEXT, total_items INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO metadata (id, name, path_display, path_lower, is_dir, synced_at) "
            "VALUES ('id:1', 'notes.paper', '/notes.paper', '/notes.paper', 0, '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO metadata (id, name, path_display, path_lower, is_dir, synced_at) "
            "VALUES ('id:2', 'report.docx', '/report.docx', '/report.docx', 0, '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO metadata (id, name, path_display, path_lower, is_dir, synced_at) "
            "VALUES ('id:3', 'Archive', '/Archive', '/archive', 1, '2025-01-01')"
        )
        conn.commit()
        yield conn
        conn.close()

    def test_migration_adds_item_type_column(self, v1_conn):
        initialize_schema(v1_conn)
        cols = {row[1] for row in v1_conn.execute("PRAGMA table_info(metadata)").fetchall()}
        assert "item_type" in cols

    def test_migration_backfills_paper(self, v1_conn):
        initialize_schema(v1_conn)
        row = v1_conn.execute("SELECT item_type FROM metadata WHERE id = 'id:1'").fetchone()
        assert row[0] == "paper"

    def test_migration_backfills_file(self, v1_conn):
        initialize_schema(v1_conn)
        row = v1_conn.execute("SELECT item_type FROM metadata WHERE id = 'id:2'").fetchone()
        assert row[0] == "file"

    def test_migration_backfills_folder(self, v1_conn):
        initialize_schema(v1_conn)
        row = v1_conn.execute("SELECT item_type FROM metadata WHERE id = 'id:3'").fetchone()
        assert row[0] == "folder"

    def test_migration_sets_schema_version(self, v1_conn):
        initialize_schema(v1_conn)
        ver = v1_conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert ver == SCHEMA_VERSION

    def test_migration_idempotent(self, v1_conn):
        initialize_schema(v1_conn)
        initialize_schema(v1_conn)
        rows = v1_conn.execute("SELECT item_type FROM metadata ORDER BY id").fetchall()
        assert [r[0] for r in rows] == ["paper", "file", "folder"]

    def test_migration_preserves_fts(self, v1_conn):
        """FTS search works after migration."""
        initialize_schema(v1_conn)
        results = v1_conn.execute(
            "SELECT * FROM metadata_fts WHERE metadata_fts MATCH 'notes'"
        ).fetchall()
        assert len(results) == 1
