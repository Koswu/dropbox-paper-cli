"""Tests for config paths and credential loading."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dropbox_paper_cli.lib.config import (
    CACHE_DB_PATH,
    CONFIG_DIR,
    DATA_DIR,
    TOKEN_PATH,
    get_app_key,
    get_app_secret,
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


class TestAppCredentials:
    """App key/secret loaded from config.json or env vars."""

    def test_get_app_key_from_env(self):
        with patch.dict(os.environ, {"DROPBOX_APP_KEY": "test-key-123"}):
            assert get_app_key() == "test-key-123"

    def test_get_app_key_from_config_file(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"app_key": "file-key-456"}))
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("dropbox_paper_cli.lib.config.APP_CONFIG_PATH", cfg),
        ):
            os.environ.pop("DROPBOX_APP_KEY", None)
            assert get_app_key() == "file-key-456"

    def test_get_app_key_raises_when_missing(self, tmp_path):
        cfg = tmp_path / "config.json"
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("dropbox_paper_cli.lib.config.APP_CONFIG_PATH", cfg),
        ):
            os.environ.pop("DROPBOX_APP_KEY", None)
            with pytest.raises(RuntimeError, match="app_key not configured"):
                get_app_key()

    def test_get_app_secret_from_env(self):
        with patch.dict(os.environ, {"DROPBOX_APP_SECRET": "secret-789"}):
            assert get_app_secret() == "secret-789"

    def test_get_app_secret_returns_empty_when_missing(self, tmp_path):
        cfg = tmp_path / "config.json"
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("dropbox_paper_cli.lib.config.APP_CONFIG_PATH", cfg),
        ):
            os.environ.pop("DROPBOX_APP_SECRET", None)
            assert get_app_secret() == ""
