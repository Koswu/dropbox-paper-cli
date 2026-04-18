"""Unit tests for the DropboxHttpClient and supporting helpers."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_httpx import HTTPXMock

from dropbox_paper_cli.lib.errors import (
    AuthenticationError,
    NotFoundError,
    PermissionError,
    ValidationError,
)
from dropbox_paper_cli.lib.http_client import (
    CONTENT_TIMEOUT,
    METADATA_TIMEOUT,
    DropboxHttpClient,
    encode_api_arg,
)
from dropbox_paper_cli.models.auth import AuthToken

# ── Fixtures ──────────────────────────────────────────────────────


def _make_token(**overrides: str | float | None) -> AuthToken:
    """Create a non-expired AuthToken for testing."""
    ns_root = overrides.get("root_namespace_id")
    ns_home = overrides.get("home_namespace_id")
    return AuthToken(
        access_token=str(overrides.get("access_token", "sl.test-access-token")),
        refresh_token=str(overrides.get("refresh_token", "test-refresh-token")),
        expires_at=float(overrides.get("expires_at", time.time() + 3600) or 0),
        account_id=str(overrides.get("account_id", "dbid:AAD_test")),
        root_namespace_id=str(ns_root) if ns_root is not None else None,
        home_namespace_id=str(ns_home) if ns_home is not None else None,
    )


@pytest.fixture
def token():
    return _make_token()


@pytest.fixture
def app_key():
    return "test_app_key_123"


# ── T005: Timeout Constants ──────────────────────────────────────


class TestTimeoutConstants:
    """Verify timeout profiles per R-006."""

    def test_metadata_timeout_values(self):
        assert METADATA_TIMEOUT.connect == 5.0
        assert METADATA_TIMEOUT.read == 30.0
        assert METADATA_TIMEOUT.pool == 5.0

    def test_content_timeout_values(self):
        assert CONTENT_TIMEOUT.connect == 5.0
        assert CONTENT_TIMEOUT.read == 30.0
        assert CONTENT_TIMEOUT.pool == 5.0


# ── T006: encode_api_arg ─────────────────────────────────────────


class TestEncodeApiArg:
    """Dropbox-API-Arg header encoding with non-ASCII escaping."""

    def test_ascii_only(self):
        params = {"path": "/test.paper"}
        result = encode_api_arg(params)
        assert json.loads(result) == params

    def test_non_ascii_escaped(self):
        params = {"path": "/日本語.paper"}
        result = encode_api_arg(params)
        # Verify non-ASCII chars are \\uXXXX encoded
        assert "\\u" in result
        # But the result should still be valid JSON when properly decoded
        assert all(ord(c) < 128 for c in result)

    def test_empty_dict(self):
        result = encode_api_arg({})
        assert result == "{}"

    def test_nested_params(self):
        params = {"path": "/test", "mode": {".tag": "overwrite"}}
        result = encode_api_arg(params)
        parsed = json.loads(result)
        assert parsed["mode"][".tag"] == "overwrite"


# ── T007: Client init ────────────────────────────────────────────


class TestClientInit:
    """Client construction stores token, key, and optional persister."""

    def test_basic_init(self, token, app_key):
        client = DropboxHttpClient(token, app_key)
        assert client._token == token
        assert client._app_key == app_key
        assert client._token_persister is None

    def test_init_with_persister(self, token, app_key):
        persister = MagicMock()
        client = DropboxHttpClient(token, app_key, token_persister=persister)
        assert client._token_persister is persister


# ── T008: Context manager ────────────────────────────────────────


class TestContextManager:
    """Async context manager creates/closes httpx.AsyncClient."""

    async def test_aenter_aexit(self, token, app_key):
        client = DropboxHttpClient(token, app_key)
        assert client._client is None
        async with client:
            assert client._client is not None
            assert isinstance(client._client, httpx.AsyncClient)
        assert client._client is None


# ── T009: Auth headers ───────────────────────────────────────────


class TestAuthHeaders:
    """Authorization header and optional path-root header."""

    def test_basic_auth_header(self, token, app_key):
        client = DropboxHttpClient(token, app_key)
        headers = client._auth_headers()
        assert headers["Authorization"] == f"Bearer {token.access_token}"
        assert "Dropbox-API-Path-Root" not in headers

    def test_path_root_header_when_namespaces_differ(self, app_key):
        token = _make_token(root_namespace_id="ns:root", home_namespace_id="ns:home")
        client = DropboxHttpClient(token, app_key)
        headers = client._auth_headers()
        path_root = json.loads(headers["Dropbox-API-Path-Root"])
        assert path_root == {".tag": "root", "root": "ns:root"}

    def test_no_path_root_when_namespaces_same(self, app_key):
        token = _make_token(root_namespace_id="ns:same", home_namespace_id="ns:same")
        client = DropboxHttpClient(token, app_key)
        headers = client._auth_headers()
        assert "Dropbox-API-Path-Root" not in headers


# ── T010: Error mapping ──────────────────────────────────────────


class TestRaiseForApiError:
    """_raise_for_api_error maps HTTP status codes to AppError hierarchy."""

    def _make_response(
        self, status_code: int, json_body: dict | None = None, text: str = ""
    ) -> httpx.Response:
        """Create a fake httpx.Response."""
        response = httpx.Response(
            status_code=status_code,
            content=json.dumps(json_body).encode() if json_body else text.encode(),
            headers={"content-type": "application/json"} if json_body else {},
            request=httpx.Request("POST", "https://api.dropboxapi.com/2/test"),
        )
        return response

    def test_400_raises_validation(self):
        resp = self._make_response(400, text="bad request")
        with pytest.raises(ValidationError, match="Bad request"):
            DropboxHttpClient._raise_for_api_error(resp)

    def test_403_raises_permission(self):
        resp = self._make_response(403, text="forbidden")
        with pytest.raises(PermissionError, match="Permission denied"):
            DropboxHttpClient._raise_for_api_error(resp)

    def test_409_not_found(self):
        resp = self._make_response(409, {"error_summary": "path/not_found/..."})
        with pytest.raises(NotFoundError, match="Not found"):
            DropboxHttpClient._raise_for_api_error(resp)

    def test_409_non_exportable(self):
        resp = self._make_response(409, {"error_summary": "non_exportable"})
        with pytest.raises(ValidationError, match="Not a Paper document"):
            DropboxHttpClient._raise_for_api_error(resp)

    def test_409_doc_deleted(self):
        resp = self._make_response(409, {"error_summary": "doc_deleted"})
        with pytest.raises(NotFoundError, match="Document is deleted"):
            DropboxHttpClient._raise_for_api_error(resp)

    def test_409_revision_mismatch(self):
        resp = self._make_response(409, {"error_summary": "revision_mismatch"})
        with pytest.raises(ValidationError, match="Revision mismatch"):
            DropboxHttpClient._raise_for_api_error(resp)

    def test_409_shared_link_already_exists(self):
        body = {
            "error_summary": "shared_link_already_exists/..",
            "error": {"shared_link_already_exists": {"url": "https://link"}},
        }
        resp = self._make_response(409, body)
        with pytest.raises(ValidationError, match="shared_link_already_exists"):
            DropboxHttpClient._raise_for_api_error(resp)


# ── T011-T012: Token refresh ─────────────────────────────────────


class TestTokenRefresh:
    """Token refresh on 401 via _handle_401 and _refresh_token."""

    async def test_refresh_token_success(self, app_key, httpx_mock: HTTPXMock):
        expired_token = _make_token(expires_at=time.time() - 100)
        client = DropboxHttpClient(expired_token, app_key)

        httpx_mock.add_response(
            url="https://api.dropboxapi.com/oauth2/token",
            json={"access_token": "new-access-token", "expires_in": 14400, "token_type": "bearer"},
        )

        async with client:
            await client._handle_401()
            assert client._token.access_token == "new-access-token"

    async def test_refresh_calls_persister(self, app_key, httpx_mock: HTTPXMock):
        expired_token = _make_token(expires_at=time.time() - 100)
        persister = MagicMock()
        client = DropboxHttpClient(expired_token, app_key, token_persister=persister)

        httpx_mock.add_response(
            url="https://api.dropboxapi.com/oauth2/token",
            json={"access_token": "new-tok", "expires_in": 14400},
        )

        async with client:
            await client._handle_401()
            persister.assert_called_once()
            assert persister.call_args[0][0].access_token == "new-tok"

    async def test_refresh_invalid_grant_raises_auth_error(self, app_key, httpx_mock: HTTPXMock):
        expired_token = _make_token(expires_at=time.time() - 100)
        client = DropboxHttpClient(expired_token, app_key)

        httpx_mock.add_response(
            url="https://api.dropboxapi.com/oauth2/token",
            status_code=400,
            json={"error": "invalid_grant", "error_description": "revoked"},
        )

        async with client:
            with pytest.raises(AuthenticationError, match="invalid or revoked"):
                await client._handle_401()

    async def test_handle_401_skips_if_not_expired(self, app_key):
        """Double-check lock: skip refresh if token is still valid."""
        token = _make_token()  # not expired
        client = DropboxHttpClient(token, app_key)
        async with client:
            original = client._token.access_token
            await client._handle_401()
            assert client._token.access_token == original


# ── T014-T016: RPC / Content-Download / Content-Upload ───────────


class TestRpcMethod:
    """rpc() sends JSON POST to api.dropboxapi.com."""

    async def test_rpc_success(self, token, app_key, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/list_folder",
            json={"entries": [], "cursor": "c1", "has_more": False},
        )

        async with DropboxHttpClient(token, app_key) as client:
            result = await client.rpc("files/list_folder", {"path": ""})
            assert result["entries"] == []
            assert result["cursor"] == "c1"

    async def test_rpc_409_not_found(self, token, app_key, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/get_metadata",
            status_code=409,
            json={"error_summary": "path/not_found/.."},
        )

        async with DropboxHttpClient(token, app_key) as client:
            with pytest.raises(NotFoundError):
                await client.rpc("files/get_metadata", {"path": "/nonexistent"})


class TestContentDownload:
    """content_download() retrieves binary content with metadata in header."""

    async def test_download_success(self, token, app_key, httpx_mock: HTTPXMock):
        metadata = {"name": "test.paper", "rev": "abc123"}
        httpx_mock.add_response(
            url="https://content.dropboxapi.com/2/files/download",
            content=b"# Hello World",
            headers={"Dropbox-API-Result": json.dumps(metadata)},
        )

        async with DropboxHttpClient(token, app_key) as client:
            content, meta = await client.content_download("files/download", {"path": "/test.paper"})
            assert content == b"# Hello World"
            assert meta["name"] == "test.paper"


class TestContentUpload:
    """content_upload() sends binary body, receives JSON response."""

    async def test_upload_success(self, token, app_key, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url="https://content.dropboxapi.com/2/files/upload",
            json={"name": "new.paper", "id": "id:abc"},
        )

        async with DropboxHttpClient(token, app_key) as client:
            result = await client.content_upload(
                "files/upload",
                {"path": "/new.paper", "mode": {".tag": "add"}},
                b"# New Document",
            )
            assert result["name"] == "new.paper"


# ── T017: 401 → refresh → retry integration ──────────────────────


class TestAutoRefreshOn401:
    """When the API returns 401, client refreshes token and retries."""

    async def test_401_triggers_refresh_and_retry(self, app_key, httpx_mock: HTTPXMock):
        expired_token = _make_token(expires_at=time.time() - 100)
        client = DropboxHttpClient(expired_token, app_key)

        # First RPC call: 401
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/list_folder",
            status_code=401,
        )
        # Token refresh: success
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/oauth2/token",
            json={"access_token": "refreshed-token", "expires_in": 14400},
        )
        # Retry after refresh: success
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/list_folder",
            json={"entries": [], "cursor": "c", "has_more": False},
        )

        async with client:
            result = await client.rpc("files/list_folder", {"path": ""})
            assert result["entries"] == []
            assert client._token.access_token == "refreshed-token"


# ── T082: Integration-level error scenario tests ──────────────────


class TestRetryIntegration:
    """End-to-end retry scenarios through the real client + retry decorator."""

    async def test_429_retry_succeeds(self, token, app_key, httpx_mock: HTTPXMock):
        """429 → retry → 200 succeeds."""
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/list_folder",
            status_code=429,
            headers={"Retry-After": "0"},
        )
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/list_folder",
            json={"entries": [], "cursor": "c", "has_more": False},
        )

        async with DropboxHttpClient(token, app_key) as client:
            result = await client.rpc("files/list_folder", {"path": ""})
            assert result["has_more"] is False

    async def test_500_retry_succeeds(self, token, app_key, httpx_mock: HTTPXMock):
        """500 → retry → 200 succeeds."""
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/list_folder",
            status_code=500,
        )
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/2/files/list_folder",
            json={"entries": [], "cursor": "c2", "has_more": False},
        )

        async with DropboxHttpClient(token, app_key) as client:
            result = await client.rpc("files/list_folder", {"path": ""})
            assert result["cursor"] == "c2"

    async def test_all_retries_exhausted_gives_clear_error(
        self, token, app_key, httpx_mock: HTTPXMock
    ):
        """All retries fail → NetworkError with clear message."""
        from dropbox_paper_cli.lib.errors import NetworkError

        for _ in range(4):  # 1 initial + 3 retries
            httpx_mock.add_response(
                url="https://api.dropboxapi.com/2/files/list_folder",
                status_code=503,
            )

        async with DropboxHttpClient(token, app_key) as client:
            with pytest.raises(NetworkError, match="Server error.*after 3 retries"):
                await client.rpc("files/list_folder", {"path": ""})


# ── T083: Concurrent 401 handling ────────────────────────────────


class TestConcurrent401:
    """Multiple concurrent 401 handlers should only trigger one token refresh."""

    async def test_concurrent_401_single_refresh(self, app_key, httpx_mock: HTTPXMock):
        """Simulate 20 concurrent _handle_401 calls, verify only one refresh occurs."""
        import asyncio

        expired_token = _make_token(expires_at=time.time() - 100)
        client = DropboxHttpClient(expired_token, app_key)

        # Only ONE refresh response — if a second refresh is attempted, it will fail
        httpx_mock.add_response(
            url="https://api.dropboxapi.com/oauth2/token",
            json={"access_token": "refreshed-tok", "expires_in": 14400},
        )

        async with client:
            # 20 concurrent _handle_401 calls — the asyncio.Lock ensures
            # only the first caller actually refreshes the token
            await asyncio.gather(*[client._handle_401() for _ in range(20)])

            assert client._token.access_token == "refreshed-tok"
            refresh_calls = [
                req for req in httpx_mock.get_requests() if "oauth2/token" in str(req.url)
            ]
            assert len(refresh_calls) == 1
