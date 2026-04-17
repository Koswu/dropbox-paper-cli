"""Shared test fixtures for the Dropbox Paper CLI test suite."""

from __future__ import annotations

from unittest.mock import MagicMock, create_autospec

import dropbox
import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_dropbox_client() -> MagicMock:
    """Provide a mock Dropbox SDK client."""
    return create_autospec(dropbox.Dropbox, instance=True)


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Provide a temporary config directory mimicking ~/.dropbox-paper-cli/."""
    config_dir = tmp_path / ".dropbox-paper-cli"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def tmp_token_path(tmp_config_dir):
    """Provide a temporary token file path."""
    return tmp_config_dir / "tokens.json"


@pytest.fixture
def tmp_cache_db_path(tmp_config_dir):
    """Provide a temporary cache DB path."""
    return tmp_config_dir / "cache.db"
