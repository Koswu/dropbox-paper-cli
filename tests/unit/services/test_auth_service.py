"""Tests for auth_service: OAuth2 flows, token CRUD, auto-refresh."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dropbox_paper_cli.models.auth import AuthToken
from dropbox_paper_cli.services.auth_service import AuthService


@pytest.fixture
def auth_service(tmp_config_dir, tmp_token_path):
    """AuthService configured with temp paths."""
    return AuthService(config_dir=tmp_config_dir, token_path=tmp_token_path)


@pytest.fixture
def sample_token():
    """A valid AuthToken for testing."""
    return AuthToken(
        access_token="sl.test_access",
        refresh_token="test_refresh",
        expires_at=9999999999.0,
        account_id="dbid:AADtest",
        uid="12345",
    )


class TestTokenPersistence:
    """Token CRUD: save, load, delete with proper file permissions."""

    def test_save_token_creates_file(self, auth_service, sample_token, tmp_token_path):
        auth_service.save_token(sample_token)
        assert tmp_token_path.exists()

    def test_save_token_correct_permissions(self, auth_service, sample_token, tmp_token_path):
        auth_service.save_token(sample_token)
        mode = tmp_token_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_save_token_valid_json(self, auth_service, sample_token, tmp_token_path):
        auth_service.save_token(sample_token)
        data = json.loads(tmp_token_path.read_text())
        assert data["access_token"] == "sl.test_access"
        assert data["account_id"] == "dbid:AADtest"

    def test_load_token(self, auth_service, sample_token, tmp_token_path):
        auth_service.save_token(sample_token)
        loaded = auth_service.load_token()
        assert loaded is not None
        assert loaded.access_token == "sl.test_access"
        assert loaded.account_id == "dbid:AADtest"

    def test_load_token_returns_none_when_missing(self, auth_service):
        assert auth_service.load_token() is None

    def test_delete_token(self, auth_service, sample_token, tmp_token_path):
        auth_service.save_token(sample_token)
        auth_service.delete_token()
        assert not tmp_token_path.exists()

    def test_delete_token_idempotent(self, auth_service):
        # Deleting when no token exists should not raise
        auth_service.delete_token()

    def test_save_creates_config_dir(self, tmp_path, sample_token):
        """If config dir doesn't exist, save_token creates it."""
        config_dir = tmp_path / "new_config"
        token_path = config_dir / "tokens.json"
        svc = AuthService(config_dir=config_dir, token_path=token_path)
        svc.save_token(sample_token)
        assert config_dir.exists()
        dir_mode = config_dir.stat().st_mode & 0o777
        assert dir_mode == 0o700


class TestPKCEFlowInitiation:
    """PKCE flow creates auth URL and processes auth code."""

    @patch("dropbox_paper_cli.services.auth_service.DropboxOAuth2FlowNoRedirect")
    def test_start_pkce_flow_returns_url(self, mock_flow_cls, auth_service):
        mock_flow = MagicMock()
        mock_flow.start.return_value = "https://www.dropbox.com/oauth2/authorize?..."
        mock_flow_cls.return_value = mock_flow

        url = auth_service.start_pkce_flow()
        assert "dropbox.com" in url
        mock_flow_cls.assert_called_once()
        # Verify PKCE is enabled
        call_kwargs = mock_flow_cls.call_args
        assert call_kwargs[1].get("use_pkce") is True or call_kwargs.kwargs.get("use_pkce") is True

    @patch("dropbox_paper_cli.services.auth_service.DropboxOAuth2FlowNoRedirect")
    def test_finish_pkce_flow_returns_token(self, mock_flow_cls, auth_service):
        from datetime import datetime, timedelta

        mock_result = MagicMock()
        mock_result.access_token = "sl.new_access"
        mock_result.refresh_token = "new_refresh"
        mock_result.expires_at = datetime.utcnow() + timedelta(hours=4)
        mock_result.account_id = "dbid:AADnew"
        mock_result.user_id = "67890"

        mock_flow = MagicMock()
        mock_flow.start.return_value = "https://example.com"
        mock_flow.finish.return_value = mock_result
        mock_flow_cls.return_value = mock_flow

        auth_service.start_pkce_flow()
        token = auth_service.finish_flow("auth_code_123")
        assert token.access_token == "sl.new_access"
        assert token.refresh_token == "new_refresh"
        assert token.account_id == "dbid:AADnew"


class TestAuthCodeFlowInitiation:
    """Authorization Code flow (--flow code) creates auth URL."""

    @patch("dropbox_paper_cli.services.auth_service.DropboxOAuth2FlowNoRedirect")
    def test_start_auth_code_flow_returns_url(self, mock_flow_cls, auth_service):
        mock_flow = MagicMock()
        mock_flow.start.return_value = "https://www.dropbox.com/oauth2/authorize?..."
        mock_flow_cls.return_value = mock_flow

        url = auth_service.start_auth_code_flow()
        assert "dropbox.com" in url


class TestGetDropboxClient:
    """get_client returns a Dropbox SDK client using stored token."""

    @patch("dropbox_paper_cli.services.auth_service.dropbox.Dropbox")
    def test_get_client_with_valid_token(self, mock_dbx_cls, auth_service, sample_token):
        auth_service.save_token(sample_token)
        client = auth_service.get_client()
        assert client is not None
        mock_dbx_cls.assert_called_once()

    def test_get_client_without_token_raises(self, auth_service):
        from dropbox_paper_cli.lib.errors import AuthenticationError

        with pytest.raises(AuthenticationError):
            auth_service.get_client()
