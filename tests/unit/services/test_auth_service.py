"""Tests for auth_service: PKCE OAuth2 flows, token CRUD, HTTP client factory."""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from dropbox_paper_cli.lib.errors import AuthenticationError
from dropbox_paper_cli.lib.http_client import DropboxHttpClient
from dropbox_paper_cli.models.auth import AuthToken
from dropbox_paper_cli.services.auth_service import AuthService, _generate_pkce_pair


@pytest.fixture
def auth_service(tmp_config_dir, tmp_token_path):
    """AuthService configured with temp paths."""
    return AuthService(config_dir=tmp_config_dir, token_path=tmp_token_path, app_key="test-app-key")


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


class TestGeneratePKCEPair:
    """_generate_pkce_pair() produces valid PKCE verifier and challenge."""

    def test_returns_two_strings(self):
        verifier, challenge = _generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_verifier_length(self):
        verifier, _ = _generate_pkce_pair()
        assert len(verifier) >= 43

    def test_challenge_is_base64url(self):
        _, challenge = _generate_pkce_pair()
        # base64url uses only [A-Za-z0-9_-], no padding '='
        assert re.fullmatch(r"[A-Za-z0-9_-]+", challenge)

    def test_pairs_are_unique(self):
        pair_a = _generate_pkce_pair()
        pair_b = _generate_pkce_pair()
        assert pair_a[0] != pair_b[0]


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
        auth_service.delete_token()

    def test_save_creates_config_dir(self, tmp_path, sample_token):
        """If config dir doesn't exist, save_token creates it."""
        config_dir = tmp_path / "new_config"
        token_path = config_dir / "tokens.json"
        svc = AuthService(config_dir=config_dir, token_path=token_path, app_key="test-app-key")
        svc.save_token(sample_token)
        assert config_dir.exists()
        dir_mode = config_dir.stat().st_mode & 0o777
        assert dir_mode == 0o700


class TestPKCEFlow:
    """PKCE flow: start produces valid URL, finish exchanges code via HTTP."""

    def test_start_pkce_flow_returns_url(self, auth_service):
        url = auth_service.start_pkce_flow()
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "dropbox.com" in parsed.netloc
        assert params["client_id"] == ["test-app-key"]
        assert params["response_type"] == ["code"]
        assert "code_challenge" in params
        assert params["code_challenge_method"] == ["S256"]

    async def test_finish_pkce_flow_returns_token(self, auth_service):
        auth_service.start_pkce_flow()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "sl.new_access",
            "refresh_token": "new_refresh",
            "expires_in": 14400,
            "account_id": "dbid:AADnew",
            "uid": "67890",
            "token_type": "bearer",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(
            "dropbox_paper_cli.services.auth_service.httpx.AsyncClient", return_value=mock_client
        ):
            token = await auth_service.finish_flow("auth_code_123")

        assert token.access_token == "sl.new_access"
        assert token.refresh_token == "new_refresh"
        assert token.account_id == "dbid:AADnew"
        # Verify the POST was called with correct data
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"]["code"] == "auth_code_123"
        assert "code_verifier" in call_kwargs[1]["data"]

    async def test_finish_flow_without_start_raises(self, auth_service):
        with pytest.raises(AuthenticationError):
            await auth_service.finish_flow("some_code")

    async def test_finish_flow_http_error_raises(self, auth_service):
        auth_service.start_pkce_flow()

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error_description": "invalid grant"}
        mock_response.text = "invalid grant"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch(
                "dropbox_paper_cli.services.auth_service.httpx.AsyncClient",
                return_value=mock_client,
            ),
            pytest.raises(AuthenticationError, match="Token exchange failed"),
        ):
            await auth_service.finish_flow("bad_code")


class TestAuthCodeFlow:
    """Authorization Code flow (--flow code) creates auth URL."""

    @patch("dropbox_paper_cli.services.auth_service.get_app_secret", return_value="test-secret")
    def test_start_auth_code_flow_returns_url(self, _mock_secret, auth_service):
        url = auth_service.start_auth_code_flow()
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "dropbox.com" in parsed.netloc
        assert params["client_id"] == ["test-app-key"]
        assert params["response_type"] == ["code"]
        # Auth code flow should NOT include code_challenge
        assert "code_challenge" not in params

    @patch("dropbox_paper_cli.services.auth_service.get_app_secret", return_value=None)
    def test_auth_code_flow_falls_back_to_pkce(self, _mock_secret, auth_service):
        """Without app_secret, auth_code flow falls back to PKCE."""
        url = auth_service.start_auth_code_flow()
        params = parse_qs(urlparse(url).query)
        assert "code_challenge" in params


class TestGetHttpClient:
    """get_http_client returns a DropboxHttpClient using stored token."""

    def test_get_http_client_with_valid_token(self, auth_service, sample_token):
        auth_service.save_token(sample_token)
        client = auth_service.get_http_client()
        assert isinstance(client, DropboxHttpClient)

    def test_get_http_client_without_token_raises(self, auth_service):
        with pytest.raises(AuthenticationError):
            auth_service.get_http_client()


class TestTokenFileCompatibility:
    """Verify token files from the old SDK-based flow can still be loaded (SC-007)."""

    def test_load_sdk_format_token_file(self, auth_service, tmp_token_path):
        """A token JSON file matching the SDK-generated format is loadable."""
        sdk_token_data = {
            "access_token": "sl.old_access_token_from_sdk",
            "refresh_token": "old_refresh_token_from_sdk",
            "account_id": "dbid:AABBC12345",
            "uid": "12345",
            "root_namespace_id": "100",
            "home_namespace_id": "100",
            "expires_at": 9999999999.0,
            "token_type": "bearer",
        }
        tmp_token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_token_path.write_text(json.dumps(sdk_token_data))

        loaded = auth_service.load_token()
        assert loaded is not None
        assert loaded.access_token == "sl.old_access_token_from_sdk"
        assert loaded.refresh_token == "old_refresh_token_from_sdk"
        assert loaded.account_id == "dbid:AABBC12345"
        assert loaded.uid == "12345"
        assert loaded.root_namespace_id == "100"
        assert loaded.home_namespace_id == "100"

        # Verify DropboxHttpClient can be initialized from it
        client = auth_service.get_http_client()
        assert isinstance(client, DropboxHttpClient)


class TestNamespaceDetection:
    """detect_and_cache_namespace and get_account_info namespace caching."""

    async def test_get_account_info_caches_namespace(self, auth_service, sample_token):
        """get_account_info should cache namespace IDs from the API response."""
        auth_service.save_token(sample_token)

        mock_client = AsyncMock(spec=DropboxHttpClient)
        mock_client._token = sample_token
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.rpc = AsyncMock(
            return_value={
                "account_id": "dbid:AADtest",
                "name": {"display_name": "Jane Doe"},
                "email": "jane@example.com",
                "root_info": {
                    ".tag": "team",
                    "root_namespace_id": "100",
                    "home_namespace_id": "200",
                },
            }
        )

        with patch.object(auth_service, "get_http_client", return_value=mock_client):
            result = await auth_service.get_account_info()

        assert result["display_name"] == "Jane Doe"
        # Verify namespace was persisted
        reloaded = auth_service.load_token()
        assert reloaded is not None
        assert reloaded.root_namespace_id == "100"
        assert reloaded.home_namespace_id == "200"

    async def test_get_account_info_skips_if_namespace_cached(self, auth_service):
        """get_account_info should not overwrite existing namespace."""
        token = AuthToken(
            access_token="sl.test",
            refresh_token="test_refresh",
            expires_at=9999999999.0,
            account_id="dbid:AADtest",
            root_namespace_id="existing_root",
            home_namespace_id="existing_home",
        )
        auth_service.save_token(token)

        mock_client = AsyncMock(spec=DropboxHttpClient)
        mock_client._token = token
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.rpc = AsyncMock(
            return_value={
                "account_id": "dbid:AADtest",
                "name": {"display_name": "Jane"},
                "email": "jane@example.com",
                "root_info": {
                    "root_namespace_id": "new_root",
                    "home_namespace_id": "new_home",
                },
            }
        )

        with patch.object(auth_service, "get_http_client", return_value=mock_client):
            await auth_service.get_account_info()

        reloaded = auth_service.load_token()
        assert reloaded.root_namespace_id == "existing_root"
        assert reloaded.home_namespace_id == "existing_home"

    async def test_detect_and_cache_namespace_team_account(self, auth_service, sample_token):
        """detect_and_cache_namespace caches namespace for team accounts."""
        auth_service.save_token(sample_token)

        mock_client = AsyncMock(spec=DropboxHttpClient)
        mock_client._token = sample_token
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.rpc = AsyncMock(
            return_value={
                "root_info": {
                    ".tag": "team",
                    "root_namespace_id": "300",
                    "home_namespace_id": "400",
                },
            }
        )

        with patch(
            "dropbox_paper_cli.services.auth_service.DropboxHttpClient",
            return_value=mock_client,
        ):
            await auth_service.detect_and_cache_namespace()

        reloaded = auth_service.load_token()
        assert reloaded.root_namespace_id == "300"
        assert reloaded.home_namespace_id == "400"

    async def test_detect_and_cache_namespace_skips_if_cached(self, auth_service):
        """detect_and_cache_namespace is a no-op if namespace is already stored."""
        token = AuthToken(
            access_token="sl.test",
            refresh_token="test_refresh",
            expires_at=9999999999.0,
            account_id="dbid:AADtest",
            root_namespace_id="cached_root",
            home_namespace_id="cached_home",
        )
        auth_service.save_token(token)

        with patch(
            "dropbox_paper_cli.services.auth_service.DropboxHttpClient",
        ) as mock_cls:
            await auth_service.detect_and_cache_namespace()
            mock_cls.assert_not_called()

    async def test_detect_and_cache_namespace_logs_on_error(self, auth_service, sample_token):
        """detect_and_cache_namespace logs a warning on API failure."""
        auth_service.save_token(sample_token)

        mock_client = AsyncMock(spec=DropboxHttpClient)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.rpc = AsyncMock(side_effect=Exception("network error"))

        with (
            patch(
                "dropbox_paper_cli.services.auth_service.DropboxHttpClient",
                return_value=mock_client,
            ),
            patch("dropbox_paper_cli.services.auth_service.logger") as mock_logger,
        ):
            await auth_service.detect_and_cache_namespace()
            mock_logger.warning.assert_called_once()

        # Namespace should still be unset
        reloaded = auth_service.load_token()
        assert reloaded.root_namespace_id is None
