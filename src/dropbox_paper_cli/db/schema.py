"""Schema DDL for the metadata cache: tables, FTS5, triggers, sync_state."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3

# ── DDL Statements ────────────────────────────────────────────────

_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS metadata (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    path_display    TEXT UNIQUE NOT NULL,
    path_lower      TEXT NOT NULL,
    is_dir          INTEGER NOT NULL DEFAULT 0,
    item_type       TEXT NOT NULL DEFAULT 'file',
    parent_path     TEXT,
    size_bytes      INTEGER,
    server_modified TEXT,
    rev             TEXT,
    content_hash    TEXT,
    url             TEXT,
    synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_metadata_parent_path ON metadata(parent_path);
CREATE INDEX IF NOT EXISTS idx_metadata_is_dir ON metadata(is_dir);
CREATE INDEX IF NOT EXISTS idx_metadata_name ON metadata(name);
"""

# Indexes that depend on columns added by migrations — applied after migrations run
_POST_MIGRATION_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_metadata_item_type ON metadata(item_type);
"""

_FTS5_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS metadata_fts USING fts5(
    name,
    path_display,
    content=metadata,
    content_rowid=rowid,
    tokenize='unicode61'
);
"""

_FTS_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS metadata_fts_insert AFTER INSERT ON metadata BEGIN
    INSERT INTO metadata_fts(rowid, name, path_display)
    VALUES (new.rowid, new.name, new.path_display);
END;
"""

_FTS_TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS metadata_fts_delete AFTER DELETE ON metadata BEGIN
    INSERT INTO metadata_fts(metadata_fts, rowid, name, path_display)
    VALUES ('delete', old.rowid, old.name, old.path_display);
END;
"""

_FTS_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS metadata_fts_update AFTER UPDATE ON metadata BEGIN
    INSERT INTO metadata_fts(metadata_fts, rowid, name, path_display)
    VALUES ('delete', old.rowid, old.name, old.path_display);
    INSERT INTO metadata_fts(rowid, name, path_display)
    VALUES (new.rowid, new.name, new.path_display);
END;
"""

_SYNC_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS sync_state (
    key             TEXT PRIMARY KEY,
    cursor          TEXT,
    last_sync_at    TEXT,
    total_items     INTEGER DEFAULT 0
);
"""

_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


# ── Migrations ────────────────────────────────────────────────────


def _get_current_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied schema version, or 0 if none."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] or 0
    except sqlite3.OperationalError:
        return 0


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add item_type column and backfill from existing data."""
    # Check if column already exists (idempotent)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
    if "item_type" in cols:
        return

    # Drop FTS triggers to avoid unnecessary churn during backfill
    conn.execute("DROP TRIGGER IF EXISTS metadata_fts_update")
    conn.execute("DROP TRIGGER IF EXISTS metadata_fts_insert")
    conn.execute("DROP TRIGGER IF EXISTS metadata_fts_delete")

    conn.execute("ALTER TABLE metadata ADD COLUMN item_type TEXT NOT NULL DEFAULT 'file'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_item_type ON metadata(item_type)")

    # Backfill: folders → 'folder', .paper → 'paper', rest stays 'file'
    conn.execute("UPDATE metadata SET item_type = 'folder' WHERE is_dir = 1")
    conn.execute("UPDATE metadata SET item_type = 'paper' WHERE is_dir = 0 AND name LIKE '%.paper'")

    # Recreate FTS triggers
    conn.executescript(_FTS_TRIGGER_INSERT + _FTS_TRIGGER_DELETE + _FTS_TRIGGER_UPDATE)

    conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (2)")
    conn.commit()


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add url column for caching sharing links."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
    if "url" in cols:
        return

    conn.execute("ALTER TABLE metadata ADD COLUMN url TEXT")
    conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (3)")
    conn.commit()


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, FTS5 virtual table, and triggers.

    Safe to call multiple times (uses IF NOT EXISTS).
    Runs migrations when upgrading from an older schema version.
    """
    conn.executescript(
        _METADATA_TABLE
        + _INDEXES
        + _FTS5_TABLE
        + _FTS_TRIGGER_INSERT
        + _FTS_TRIGGER_DELETE
        + _FTS_TRIGGER_UPDATE
        + _SYNC_STATE_TABLE
        + _SCHEMA_VERSION_TABLE
    )

    current = _get_current_version(conn)

    if current < 2:
        _migrate_v1_to_v2(conn)
        # Rebuild FTS index to ensure consistency after migration
        conn.execute("INSERT INTO metadata_fts(metadata_fts) VALUES('rebuild')")
        conn.commit()

    if current < 3:
        _migrate_v2_to_v3(conn)

    # Post-migration indexes (depend on columns added by migrations)
    conn.executescript(_POST_MIGRATION_INDEXES)

    # Record latest schema version
    cursor = conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (SCHEMA_VERSION,)
    )
    if cursor.fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
