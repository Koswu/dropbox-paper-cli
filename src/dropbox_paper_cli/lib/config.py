"""Configuration paths, app key, and default values."""

from __future__ import annotations

import os
from pathlib import Path

# Base config directory — default ~/.dropbox-paper-cli/
CONFIG_DIR: Path = Path(os.environ.get("PAPER_CLI_CONFIG_DIR", Path.home() / ".dropbox-paper-cli"))

# Token storage
TOKEN_PATH: Path = CONFIG_DIR / "tokens.json"

# SQLite cache database
CACHE_DB_PATH: Path = CONFIG_DIR / "cache.db"

# Dropbox app key (public client identifier — not a secret)
APP_KEY: str = "REDACTED_APP_KEY"
