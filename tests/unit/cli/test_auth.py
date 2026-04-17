"""Tests for auth CLI commands: login, logout, status with human-readable and --json output."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from dropbox_paper_cli.app import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_auth_service():
    """Patch the auth service used by CLI commands."""
    with patch("dropbox_paper_cli.cli.auth._get_auth_service") as mock_get:
        svc = MagicMock()
        mock_get.return_value = svc
        yield svc


class TestAuthLogin:
    """paper auth login initiates OAuth2 flow."""

    def test_login_pkce_prompts_for_code(self, runner, mock_auth_service):
        mock_auth_service.start_pkce_flow.return_value = "https://dropbox.com/oauth2/authorize?..."

        mock_token = MagicMock()
        mock_token.account_id = "dbid:AADtest"
        mock_auth_service.finish_flow.return_value = mock_token

        # Mock getting user info
        mock_client = MagicMock()
        mock_account = MagicMock()
        mock_account.name.display_name = "Jane Doe"
        mock_account.email = "jane@example.com"
        mock_client.users_get_current_account.return_value = mock_account
        mock_auth_service.get_client.return_value = mock_client

        result = runner.invoke(app, ["auth", "login"], input="auth_code_here\n")
        assert result.exit_code == 0
        assert "Authorization URL" in result.stdout or "Jane Doe" in result.stdout

    def test_login_json_output(self, runner, mock_auth_service):
        mock_auth_service.start_pkce_flow.return_value = "https://dropbox.com/oauth2/authorize?..."

        mock_token = MagicMock()
        mock_token.account_id = "dbid:AADtest"
        mock_auth_service.finish_flow.return_value = mock_token
        mock_auth_service.save_token.return_value = None

        mock_client = MagicMock()
        mock_account = MagicMock()
        mock_account.name.display_name = "Jane Doe"
        mock_account.email = "jane@example.com"
        mock_client.users_get_current_account.return_value = mock_account
        mock_auth_service.get_client.return_value = mock_client

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

        mock_token = MagicMock()
        mock_token.account_id = "dbid:AADtest"
        mock_auth_service.finish_flow.return_value = mock_token

        mock_client = MagicMock()
        mock_account = MagicMock()
        mock_account.name.display_name = "Bob"
        mock_account.email = "bob@example.com"
        mock_client.users_get_current_account.return_value = mock_account
        mock_auth_service.get_client.return_value = mock_client

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
        mock_token = MagicMock()
        mock_token.account_id = "dbid:AADtest"
        mock_token.is_expired = False
        mock_token.expires_at = 9999999999.0
        mock_auth_service.load_token.return_value = mock_token

        mock_client = MagicMock()
        mock_account = MagicMock()
        mock_account.name.display_name = "Jane Doe"
        mock_account.email = "jane@example.com"
        mock_client.users_get_current_account.return_value = mock_account
        mock_auth_service.get_client.return_value = mock_client

        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Jane Doe" in result.stdout

    def test_status_not_authenticated(self, runner, mock_auth_service):
        mock_auth_service.load_token.return_value = None
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.stdout

    def test_status_json_authenticated(self, runner, mock_auth_service):
        mock_token = MagicMock()
        mock_token.account_id = "dbid:AADtest"
        mock_token.is_expired = False
        mock_token.expires_at = 9999999999.0
        mock_auth_service.load_token.return_value = mock_token

        mock_client = MagicMock()
        mock_account = MagicMock()
        mock_account.name.display_name = "Jane Doe"
        mock_account.email = "jane@example.com"
        mock_client.users_get_current_account.return_value = mock_account
        mock_auth_service.get_client.return_value = mock_client

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
