"""Shared test fixtures for the Dropbox Paper CLI test suite."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from dropbox_paper_cli.lib.http_client import DropboxHttpClient
from dropbox_paper_cli.models.auth import AuthToken


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Provide a mock DropboxHttpClient with async methods."""
    client = AsyncMock(spec=DropboxHttpClient)
    client.rpc = AsyncMock()
    client.content_download = AsyncMock()
    client.content_upload = AsyncMock()
    # Context manager support
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture
def sample_token() -> AuthToken:
    """Provide a non-expired AuthToken for testing."""
    return AuthToken(
        access_token="sl.test-access-token",
        refresh_token="test-refresh-token",
        expires_at=time.time() + 3600,
        account_id="dbid:AAD_test",
    )


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
