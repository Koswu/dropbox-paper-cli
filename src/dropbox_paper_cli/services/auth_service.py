"""Auth service: OAuth2 PKCE/AuthCode flows, token CRUD, async HTTP client factory."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import stat
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from dropbox_paper_cli.lib.config import CONFIG_DIR, TOKEN_PATH, get_app_key, get_app_secret
from dropbox_paper_cli.lib.errors import AuthenticationError
from dropbox_paper_cli.lib.http_client import DropboxHttpClient
from dropbox_paper_cli.models.auth import AuthToken

_AUTH_BASE_URL = "https://www.dropbox.com/oauth2/authorize"
_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256).

    Returns:
        (code_verifier, code_challenge) tuple.
    """
    verifier = secrets.token_urlsafe(96)[:128]  # 43–128 chars
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class AuthService:
    """Manages OAuth2 authentication flows and token persistence.

    Supports:
    - PKCE flow (no server required, recommended for CLI)
    - Authorization Code flow (for environments with redirect server)
    - Secure token storage with atomic writes and 0600 permissions
    - DropboxHttpClient factory with auto token refresh
    """

    def __init__(
        self,
        *,
        config_dir: Path | None = None,
        token_path: Path | None = None,
        app_key: str | None = None,
    ) -> None:
        self._config_dir = config_dir or CONFIG_DIR
        self._token_path = token_path or TOKEN_PATH
        self._app_key = app_key or get_app_key()
        self._code_verifier: str | None = None
        self._flow_type: str | None = None

    # ── OAuth2 Flows ──────────────────────────────────────────────

    def start_pkce_flow(self) -> str:
        """Start OAuth2 PKCE flow. Returns the authorization URL."""
        verifier, challenge = _generate_pkce_pair()
        self._code_verifier = verifier
        self._flow_type = "pkce"
        params = {
            "client_id": self._app_key,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "token_access_type": "offline",
        }
        return f"{_AUTH_BASE_URL}?{urlencode(params)}"

    def start_auth_code_flow(self) -> str:
        """Start OAuth2 Authorization Code flow. Returns the authorization URL."""
        app_secret = get_app_secret()
        if app_secret:
            self._flow_type = "auth_code"
        else:
            # Fall back to PKCE
            return self.start_pkce_flow()
        params = {
            "client_id": self._app_key,
            "response_type": "code",
            "token_access_type": "offline",
        }
        return f"{_AUTH_BASE_URL}?{urlencode(params)}"

    async def finish_flow(self, auth_code: str) -> AuthToken:
        """Complete the OAuth2 flow with the authorization code.

        Returns the AuthToken with access and refresh tokens.
        """
        if self._flow_type is None:
            raise AuthenticationError(
                "No OAuth2 flow in progress. Call start_pkce_flow() or start_auth_code_flow() first.",
                code="AUTH_REQUIRED",
            )
        data: dict = {
            "code": auth_code.strip(),
            "grant_type": "authorization_code",
            "client_id": self._app_key,
        }
        if self._flow_type == "pkce" and self._code_verifier:
            data["code_verifier"] = self._code_verifier
        elif self._flow_type == "auth_code":
            app_secret = get_app_secret()
            if app_secret:
                data["client_secret"] = app_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(_TOKEN_URL, data=data)

        if response.status_code != 200:
            try:
                body = response.json()
                msg = body.get("error_description", body.get("error", response.text))
            except Exception:
                msg = response.text
            raise AuthenticationError(f"Token exchange failed: {msg}")

        result = response.json()
        expires_in = result.get("expires_in", 14400)
        token = AuthToken(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            expires_at=time.time() + expires_in,
            account_id=result.get("account_id", ""),
            uid=result.get("uid"),
            token_type=result.get("token_type", "bearer"),
        )
        return token

    # ── Token Persistence ─────────────────────────────────────────

    def save_token(self, token: AuthToken) -> None:
        """Persist token to disk with atomic write and restrictive permissions."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(self._config_dir, 0o700)

        data = json.dumps(token.to_dict(), indent=2)

        fd, tmp_path = tempfile.mkstemp(dir=self._config_dir, prefix=".tokens_", suffix=".tmp")
        try:
            os.write(fd, data.encode())
            os.close(fd)
            fd = -1  # mark as closed
            if sys.platform != "win32":
                os.chmod(tmp_path, 0o600)
            else:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_path, self._token_path)
        except Exception:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def load_token(self) -> AuthToken | None:
        """Load token from disk. Returns None if no token file exists."""
        if not self._token_path.exists():
            return None
        try:
            data = json.loads(self._token_path.read_text())
            return AuthToken.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def delete_token(self) -> None:
        """Delete the stored token file."""
        if self._token_path.exists():
            self._token_path.unlink()

    # ── HTTP Client Factory ───────────────────────────────────────

    def get_http_client(self) -> DropboxHttpClient:
        """Create a DropboxHttpClient using stored token.

        The client is configured with auto-refresh via the token_persister.

        Returns:
            DropboxHttpClient ready for use as async context manager.

        Raises:
            AuthenticationError: If no token is stored.
        """
        token = self.load_token()
        if token is None:
            raise AuthenticationError(
                "Not authenticated. Run 'paper auth login' first.",
                code="AUTH_REQUIRED",
            )
        return DropboxHttpClient(
            token=token,
            app_key=self._app_key,
            token_persister=self.save_token,
        )

    async def get_account_info(self) -> dict:
        """Fetch the current user's account info via the API.

        Returns:
            Dict with account_id, display_name, email.
        """
        client = self.get_http_client()
        async with client:
            result = await client.rpc("users/get_current_account")
            name = result.get("name", {})
            return {
                "account_id": result.get("account_id", ""),
                "display_name": name.get("display_name", ""),
                "email": result.get("email", ""),
            }

    async def detect_and_cache_namespace(self) -> None:
        """Detect team/personal namespace and persist to token.

        For team accounts, this caches root_namespace_id and home_namespace_id
        in the token file so DropboxHttpClient can set the path-root header.
        """
        token = self.load_token()
        if token is None:
            return
        if token.root_namespace_id and token.home_namespace_id:
            return  # Already cached

        try:
            client = DropboxHttpClient(
                token=token,
                app_key=self._app_key,
                token_persister=self.save_token,
            )
            async with client:
                result = await client.rpc("users/get_current_account")
                root_info = result.get("root_info", {})
                root_ns = root_info.get("root_namespace_id")
                home_ns = root_info.get("home_namespace_id")
                if root_ns:
                    updated = AuthToken(
                        access_token=client._token.access_token,
                        refresh_token=client._token.refresh_token,
                        expires_at=client._token.expires_at,
                        account_id=client._token.account_id,
                        uid=client._token.uid,
                        token_type=client._token.token_type,
                        root_namespace_id=root_ns,
                        home_namespace_id=home_ns,
                    )
                    self.save_token(updated)
        except Exception:
            pass
