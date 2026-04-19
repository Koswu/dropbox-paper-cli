"""CacheDatabase context manager with WAL mode and corruption recovery."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dropbox_paper_cli.db.schema import initialize_schema
from dropbox_paper_cli.lib.config import CACHE_DB_PATH


class CacheDatabase:
    """SQLite database connection manager for the metadata cache.

    Features:
    - WAL mode for better concurrent access
    - Corruption recovery: deletes and recreates on DatabaseError
    - Context manager for clean resource handling
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or CACHE_DB_PATH
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> CacheDatabase:
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        self.close()

    def _connect(self) -> None:
        """Open the database connection with WAL mode and initialize schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA case_sensitive_like=ON")
            initialize_schema(self._conn)
        except sqlite3.DatabaseError:
            # Corruption recovery: delete and recreate
            self.close()
            if self._db_path.exists():
                os.unlink(self._db_path)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA case_sensitive_like=ON")
            initialize_schema(self._conn)

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active database connection."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Use as a context manager.")
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
