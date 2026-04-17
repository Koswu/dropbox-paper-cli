"""Configuration paths, app key, and default values."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_APP_NAME = "dropbox-paper-cli"

# XDG base directories
_xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
_xdg_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

# App directories following XDG spec
CONFIG_DIR: Path = Path(os.environ.get("PAPER_CLI_CONFIG_DIR", _xdg_config / _APP_NAME))
DATA_DIR: Path = Path(os.environ.get("PAPER_CLI_DATA_DIR", _xdg_data / _APP_NAME))

# Token storage (config — user-specific settings)
TOKEN_PATH: Path = CONFIG_DIR / "tokens.json"

# SQLite cache database (data — persistent application data)
CACHE_DB_PATH: Path = DATA_DIR / "cache.db"

# Dropbox app key (public client identifier — not a secret)
APP_KEY: str = "REDACTED_APP_KEY"


def _migrate_legacy_dir() -> None:
    """Move files from legacy ~/.dropbox-paper-cli/ to XDG locations."""
    legacy = Path.home() / ".dropbox-paper-cli"
    if not legacy.is_dir():
        return

    # Migrate tokens.json → CONFIG_DIR
    old_tokens = legacy / "tokens.json"
    if old_tokens.exists() and not TOKEN_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_tokens), str(TOKEN_PATH))

    # Migrate cache.db (+ WAL/SHM) → DATA_DIR
    old_db = legacy / "cache.db"
    if old_db.exists() and not CACHE_DB_PATH.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            src = legacy / f"cache.db{suffix}"
            if src.exists():
                shutil.move(str(src), str(DATA_DIR / f"cache.db{suffix}"))

    # Remove legacy dir if empty
    try:
        legacy.rmdir()
    except OSError:
        pass


_migrate_legacy_dir()
