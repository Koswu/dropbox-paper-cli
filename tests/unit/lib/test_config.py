"""Tests for config paths, app key, and default values."""

from __future__ import annotations

from pathlib import Path

from dropbox_paper_cli.lib.config import (
    APP_KEY,
    CACHE_DB_PATH,
    CONFIG_DIR,
    DATA_DIR,
    TOKEN_PATH,
)


class TestConfigPaths:
    """Config paths follow XDG base directory spec."""

    def test_config_dir_is_under_xdg_config(self):
        assert "dropbox-paper-cli" in str(CONFIG_DIR)
        assert ".config" in str(CONFIG_DIR) or "PAPER_CLI_CONFIG_DIR" in str(CONFIG_DIR)

    def test_config_dir_is_path(self):
        assert isinstance(CONFIG_DIR, Path)

    def test_data_dir_is_path(self):
        assert isinstance(DATA_DIR, Path)

    def test_token_path_is_json_file(self):
        assert TOKEN_PATH.name == "tokens.json"
        assert TOKEN_PATH.parent == CONFIG_DIR

    def test_cache_db_path_is_db_file(self):
        assert CACHE_DB_PATH.name == "cache.db"
        assert CACHE_DB_PATH.parent == DATA_DIR


class TestAppKey:
    """APP_KEY is the configured Dropbox app key."""

    def test_app_key_is_nonempty_string(self):
        assert isinstance(APP_KEY, str)
        assert len(APP_KEY) > 0

    def test_app_key_value(self):
        assert APP_KEY == "REDACTED_APP_KEY"
