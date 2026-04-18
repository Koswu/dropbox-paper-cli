"""Configuration paths, app credentials, and default values."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
from pathlib import Path

_APP_NAME = "dropbox-paper-cli"


def _default_config_dir() -> Path:
    """Platform-aware default config directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / _APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME
    # Linux / other: XDG
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / _APP_NAME


def _default_data_dir() -> Path:
    """Platform-aware default data directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / _APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME
    # Linux / other: XDG
    xdg = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return xdg / _APP_NAME


CONFIG_DIR: Path = Path(os.environ.get("PAPER_CLI_CONFIG_DIR", _default_config_dir()))
DATA_DIR: Path = Path(os.environ.get("PAPER_CLI_DATA_DIR", _default_data_dir()))

# Token storage (config — user-specific settings)
TOKEN_PATH: Path = CONFIG_DIR / "tokens.json"

# App config file
APP_CONFIG_PATH: Path = CONFIG_DIR / "config.json"

# SQLite cache database (data — persistent application data)
CACHE_DB_PATH: Path = DATA_DIR / "cache.db"


def _load_app_config() -> dict:
    """Load app config from config.json, return empty dict if missing."""
    if APP_CONFIG_PATH.exists():
        try:
            return json.loads(APP_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def get_app_key() -> str:
    """Get Dropbox app_key from config.json or DROPBOX_APP_KEY env var."""
    key = os.environ.get("DROPBOX_APP_KEY", "")
    if key:
        return key
    cfg = _load_app_config()
    key = cfg.get("app_key", "")
    if not key:
        raise RuntimeError(
            "Dropbox app_key not configured. "
            "Set it in config.json or DROPBOX_APP_KEY env var.\n"
            f"  Config file: {APP_CONFIG_PATH}\n"
            "  See: https://www.dropbox.com/developers/apps"
        )
    return key


def get_app_secret() -> str:
    """Get Dropbox app_secret from config.json or DROPBOX_APP_SECRET env var.

    Returns empty string if not set (PKCE flow will be used).
    """
    secret = os.environ.get("DROPBOX_APP_SECRET", "")
    if secret:
        return secret
    cfg = _load_app_config()
    return cfg.get("app_secret", "")


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
    with contextlib.suppress(OSError):
        legacy.rmdir()


_migrate_legacy_dir()
