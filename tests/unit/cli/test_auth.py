"""Tests for auth CLI commands: login, logout, status with human-readable and --json output."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from dropbox_paper_cli.app import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_auth_service():
    """Patch the auth service used by CLI commands.

    Async methods (finish_flow, get_account_info) use AsyncMock so that
    asyncio.run() in the CLI can await them correctly.
    """
    with patch("dropbox_paper_cli.cli.auth._get_auth_service") as mock_get:
        svc = MagicMock()
        svc.finish_flow = AsyncMock()
        svc.get_account_info = AsyncMock()
        mock_get.return_value = svc
        yield svc


def _make_token(account_id: str = "dbid:AADtest") -> MagicMock:
    """Create a mock token with sensible defaults."""
    token = MagicMock()
    token.account_id = account_id
    token.is_expired = False
    token.expires_at = 9999999999.0
    token.root_namespace_id = None
    token.home_namespace_id = None
    return token


def _set_account_info(
    svc: MagicMock,
    display_name: str = "Jane Doe",
    email: str = "jane@example.com",
) -> None:
    """Configure mock auth service to return account info dict."""
    svc.get_account_info.return_value = {
        "display_name": display_name,
        "email": email,
    }


class TestAuthLogin:
    """paper auth login initiates OAuth2 flow."""

    def test_login_pkce_prompts_for_code(self, runner, mock_auth_service):
        mock_auth_service.start_pkce_flow.return_value = "https://dropbox.com/oauth2/authorize?..."

        mock_token = _make_token()
        mock_auth_service.finish_flow.return_value = mock_token
        _set_account_info(mock_auth_service)

        result = runner.invoke(app, ["auth", "login"], input="auth_code_here\n")
        assert result.exit_code == 0
        assert "Authorization URL" in result.stdout or "Jane Doe" in result.stdout

    def test_login_json_output(self, runner, mock_auth_service):
        mock_auth_service.start_pkce_flow.return_value = "https://dropbox.com/oauth2/authorize?..."

        mock_token = _make_token()
        mock_auth_service.finish_flow.return_value = mock_token
        mock_auth_service.save_token.return_value = None
        _set_account_info(mock_auth_service)

        result = runner.invoke(app, ["--json", "auth", "login"], input="auth_code_here\n")
        assert result.exit_code == 0
        # Extract the JSON line from output (prompt text precedes it)
        lines = result.stdout.strip().split("\n")
        json_line = next(line for line in lines if line.startswith("{"))
        data = json.loads(json_line)
        assert data["status"] == "authenticated"
        assert data["display_name"] == "Jane Doe"

    def test_login_with_code_flow(self, runner, mock_auth_service):
        mock_auth_service.start_auth_code_flow.return_value = (
            "https://dropbox.com/oauth2/authorize?..."
        )

        mock_token = _make_token()
        mock_auth_service.finish_flow.return_value = mock_token
        _set_account_info(mock_auth_service, display_name="Bob", email="bob@example.com")

        result = runner.invoke(app, ["auth", "login", "--flow", "code"], input="code123\n")
        assert result.exit_code == 0


class TestAuthLogout:
    """paper auth logout clears stored credentials."""

    def test_logout_success(self, runner, mock_auth_service):
        mock_auth_service.delete_token.return_value = None
        result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Credentials removed" in result.stdout

    def test_logout_json_output(self, runner, mock_auth_service):
        mock_auth_service.delete_token.return_value = None
        result = runner.invoke(app, ["--json", "auth", "logout"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "logged_out"


class TestAuthStatus:
    """paper auth status shows current authentication state."""

    def test_status_authenticated(self, runner, mock_auth_service):
        mock_token = _make_token()
        mock_auth_service.load_token.return_value = mock_token
        _set_account_info(mock_auth_service)

        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Jane Doe" in result.stdout

    def test_status_not_authenticated(self, runner, mock_auth_service):
        mock_auth_service.load_token.return_value = None
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.stdout

    def test_status_json_authenticated(self, runner, mock_auth_service):
        mock_token = _make_token()
        mock_auth_service.load_token.return_value = mock_token
        _set_account_info(mock_auth_service)

        result = runner.invoke(app, ["--json", "auth", "status"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["authenticated"] is True
        assert data["display_name"] == "Jane Doe"
        assert data["email"] == "jane@example.com"

    def test_status_json_not_authenticated(self, runner, mock_auth_service):
        mock_auth_service.load_token.return_value = None
        result = runner.invoke(app, ["--json", "auth", "status"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["authenticated"] is False
