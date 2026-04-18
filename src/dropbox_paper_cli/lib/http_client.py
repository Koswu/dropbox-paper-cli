"""Central async HTTP client for direct Dropbox API v2 communication.

Replaces the Dropbox SDK with httpx AsyncClient. Provides three request
patterns: RPC (JSON in/out), content-download (binary body + metadata header),
and content-upload (binary body, JSON response).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from dropbox_paper_cli.lib.errors import (
    AuthenticationError,
    NetworkError,
    NotFoundError,
    PermissionError,
    ValidationError,
)
from dropbox_paper_cli.lib.retry import with_retry
from dropbox_paper_cli.models.auth import AuthToken

__all__ = [
    "CONTENT_TIMEOUT",
    "DropboxHttpClient",
    "METADATA_TIMEOUT",
    "encode_api_arg",
]

logger = logging.getLogger("dropbox_paper_cli.lib.http_client")

# ── Timeout Profiles (R-006) ─────────────────────────────────────

METADATA_TIMEOUT = httpx.Timeout(100.0, connect=10.0, read=100.0, pool=10.0)
CONTENT_TIMEOUT = httpx.Timeout(30.0, connect=5.0, read=30.0, pool=5.0)

# ── API Base URLs ─────────────────────────────────────────────────

_RPC_BASE = "https://api.dropboxapi.com"
_CONTENT_BASE = "https://content.dropboxapi.com"


# ── Header Encoding ───────────────────────────────────────────────


def encode_api_arg(params: dict) -> str:
    """Encode parameters for the Dropbox-API-Arg header.

    Characters outside the ASCII printable range (codepoints > 127) are escaped
    using ``\\uXXXX`` notation per the Dropbox API specification.
    """
    raw = json.dumps(params, separators=(",", ":"))
    return "".join(c if ord(c) < 128 else f"\\u{ord(c):04x}" for c in raw)


# ── HTTP Client ───────────────────────────────────────────────────


class DropboxHttpClient:
    """Async HTTP client wrapping all Dropbox API v2 communication.

    Usage::

        async with DropboxHttpClient(token, app_key) as client:
            data = await client.rpc("files/list_folder", {"path": ""})
    """

    def __init__(
        self,
        token: AuthToken,
        app_key: str,
        *,
        token_persister: Callable[[AuthToken], None] | None = None,
    ) -> None:
        self._token = token
        self._app_key = app_key
        self._token_persister = token_persister
        self._refresh_lock = asyncio.Lock()
        self._logger = logger
        self._client: httpx.AsyncClient | None = None

    # ── Async Context Manager ─────────────────────────────────────

    async def __aenter__(self) -> DropboxHttpClient:
        self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Auth Headers ──────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Return Authorization header and optional path-root header."""
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token.access_token}",
        }
        if (
            self._token.root_namespace_id
            and self._token.home_namespace_id
            and self._token.root_namespace_id != self._token.home_namespace_id
        ):
            headers["Dropbox-API-Path-Root"] = json.dumps(
                {".tag": "root", "root": self._token.root_namespace_id}
            )
        return headers

    # ── Error Mapping (R-008) ─────────────────────────────────────

    @staticmethod
    def _raise_for_api_error(response: httpx.Response) -> None:
        """Parse Dropbox error JSON and raise the appropriate AppError."""
        status = response.status_code

        if status == 400:
            raise ValidationError(f"Bad request: {response.text}")

        if status == 403:
            raise PermissionError(f"Permission denied: {response.text}")

        # 409 = Dropbox endpoint-specific error
        if status == 409:
            try:
                body = response.json()
            except Exception:
                raise ValidationError(f"API error: {response.text}") from None
            summary = body.get("error_summary", "")

            # Paper-specific patterns
            if "non_exportable" in summary:
                raise ValidationError("Not a Paper document")
            if "invalid_file_extension" in summary:
                raise ValidationError("Path must end with .paper")
            if "email_unverified" in summary:
                raise ValidationError("Email must be verified")
            if "paper_disabled" in summary:
                raise ValidationError("Paper is disabled for this team")
            if "doc_archived" in summary:
                raise ValidationError("Document is archived")
            if "doc_deleted" in summary:
                raise NotFoundError("Document is deleted")
            if "revision_mismatch" in summary:
                raise ValidationError("Revision mismatch")

            # General patterns
            if "not_found" in summary:
                raise NotFoundError(f"Not found: {summary}")
            if "access_error" in summary:
                raise PermissionError(f"Access denied: {summary}")
            if "conflict" in summary:
                raise ValidationError(f"Conflict: {summary}")
            if "shared_link_already_exists" in summary:
                # Special: caller handles this
                raise ValidationError(f"shared_link_already_exists:{json.dumps(body)}")

            raise ValidationError(f"API error: {summary}")

        # Catch-all for other non-2xx statuses
        raise NetworkError(f"HTTP {status}: {response.text}")

    # ── Token Refresh (R-004) ─────────────────────────────────────

    async def _handle_401(self) -> None:
        """Double-check lock token refresh."""
        async with self._refresh_lock:
            if not self._token.is_expired:
                return  # Another task already refreshed
            new_token = await self._refresh_token()
            self._token = new_token
            if self._token_persister:
                self._token_persister(self._token)

    async def _refresh_token(self) -> AuthToken:
        """POST to oauth2/token to refresh the access token."""
        assert self._client is not None
        response = await self._client.post(
            f"{_RPC_BASE}/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._token.refresh_token,
                "client_id": self._app_key,
            },
            timeout=METADATA_TIMEOUT,
        )
        if response.status_code != 200:
            try:
                body = response.json()
            except Exception:
                body = {}
            if body.get("error") == "invalid_grant":
                raise AuthenticationError(
                    "Refresh token is invalid or revoked. Run 'paper auth login' to re-authenticate."
                )
            raise AuthenticationError(f"Token refresh failed: {response.text}")

        data = response.json()
        return AuthToken(
            access_token=data["access_token"],
            refresh_token=self._token.refresh_token,
            expires_at=time.time() + data.get("expires_in", 14400),
            account_id=self._token.account_id,
            uid=self._token.uid,
            token_type=data.get("token_type", "bearer"),
            root_namespace_id=self._token.root_namespace_id,
            home_namespace_id=self._token.home_namespace_id,
        )

    # ── Low-Level Request (R-010 logging) ─────────────────────────

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute request with auth, 401 retry, DEBUG logging."""
        assert self._client is not None
        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())

        start = time.monotonic()
        try:
            response = await self._client.request(method, url, headers=headers, **kwargs)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            duration_ms = (time.monotonic() - start) * 1000
            self._logger.debug("%s %s -> ERROR (%.0fms): %s", method, url, duration_ms, exc)
            raise
        duration_ms = (time.monotonic() - start) * 1000
        self._logger.debug("%s %s -> %d (%.0fms)", method, url, response.status_code, duration_ms)

        # Handle 401: refresh token and retry once
        if response.status_code == 401:
            await self._handle_401()
            # Update headers with new token
            headers.update(self._auth_headers())
            start = time.monotonic()
            response = await self._client.request(method, url, headers=headers, **kwargs)
            duration_ms = (time.monotonic() - start) * 1000
            self._logger.debug(
                "%s %s -> %d (%.0fms) [after refresh]",
                method,
                url,
                response.status_code,
                duration_ms,
            )

        if response.status_code >= 400 and response.status_code not in (429, 500, 503):
            self._raise_for_api_error(response)

        # 429/500/503 are handled by @with_retry at the caller level
        if response.status_code in (429, 500, 503):
            raise httpx.HTTPStatusError(
                message=f"HTTP {response.status_code}",
                request=response.request,
                response=response,
            )

        return response

    # ── Public API Methods ────────────────────────────────────────

    @with_retry()
    async def rpc(
        self,
        endpoint: str,
        params: dict | None = None,
        *,
        timeout: httpx.Timeout = METADATA_TIMEOUT,
    ) -> dict:
        """RPC endpoint call: JSON in/out via api.dropboxapi.com."""
        url = f"{_RPC_BASE}/2/{endpoint}"
        # Dropbox RPC endpoints expect JSON body; use b"null" when no params
        # (the API rejects empty body with Content-Type: application/json)
        if params is not None:
            body_kwargs: dict[str, Any] = {"json": params}
        else:
            body_kwargs = {
                "content": b"null",
                "headers": {"Content-Type": "application/json"},
            }
        response = await self._request(
            "POST",
            url,
            **body_kwargs,
            timeout=timeout,
        )
        return response.json()

    @with_retry()
    async def content_download(
        self,
        endpoint: str,
        params: dict,
        *,
        timeout: httpx.Timeout = CONTENT_TIMEOUT,
    ) -> tuple[bytes, dict]:
        """Content-download: binary body + Dropbox-API-Result metadata header."""
        url = f"{_CONTENT_BASE}/2/{endpoint}"
        response = await self._request(
            "POST",
            url,
            headers={"Dropbox-API-Arg": encode_api_arg(params)},
            timeout=timeout,
        )
        # Parse metadata from response header
        result_header = response.headers.get("Dropbox-API-Result", "{}")
        metadata = json.loads(result_header)
        return response.content, metadata

    @with_retry()
    async def content_upload(
        self,
        endpoint: str,
        params: dict,
        data: bytes,
        *,
        timeout: httpx.Timeout = CONTENT_TIMEOUT,
        host: str = "content",
    ) -> dict:
        """Content-upload: binary body, JSON response.

        Args:
            host: "content" for content.dropboxapi.com (default),
                  "api" for api.dropboxapi.com (paper create/update endpoints).
        """
        base = _RPC_BASE if host == "api" else _CONTENT_BASE
        url = f"{base}/2/{endpoint}"
        response = await self._request(
            "POST",
            url,
            content=data,
            headers={
                "Dropbox-API-Arg": encode_api_arg(params),
                "Content-Type": "application/octet-stream",
            },
            timeout=timeout,
        )
        return response.json()
