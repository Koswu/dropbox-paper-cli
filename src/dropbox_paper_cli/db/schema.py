"""Schema DDL for the metadata cache: tables, FTS5, triggers, sync_state."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

# ── DDL Statements ────────────────────────────────────────────────

_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS metadata (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    path_display    TEXT UNIQUE NOT NULL,
    path_lower      TEXT NOT NULL,
    is_dir          INTEGER NOT NULL DEFAULT 0,
    parent_path     TEXT,
    size_bytes      INTEGER,
    server_modified TEXT,
    rev             TEXT,
    content_hash    TEXT,
    synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_metadata_parent_path ON metadata(parent_path);
CREATE INDEX IF NOT EXISTS idx_metadata_is_dir ON metadata(is_dir);
CREATE INDEX IF NOT EXISTS idx_metadata_name ON metadata(name);
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


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, FTS5 virtual table, and triggers.

    Safe to call multiple times (uses IF NOT EXISTS).
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

    # Record schema version if not already present
    cursor = conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (SCHEMA_VERSION,)
    )
    if cursor.fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
