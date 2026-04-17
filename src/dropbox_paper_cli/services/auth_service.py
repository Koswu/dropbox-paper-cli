"""Auth service: OAuth2 PKCE/AuthCode flows, token CRUD, auto-refresh client."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

import dropbox
import dropbox.common
from dropbox.oauth import DropboxOAuth2FlowNoRedirect

from dropbox_paper_cli.lib.config import CONFIG_DIR, TOKEN_PATH, get_app_key, get_app_secret
from dropbox_paper_cli.lib.errors import AuthenticationError
from dropbox_paper_cli.models.auth import AuthToken


class AuthService:
    """Manages OAuth2 authentication flows and token persistence.

    Supports:
    - PKCE flow (no server required, recommended for CLI)
    - Authorization Code flow (for environments with redirect server)
    - Secure token storage with atomic writes and 0600 permissions
    - Auto-refresh via Dropbox SDK
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
        self._flow: DropboxOAuth2FlowNoRedirect | None = None
        self._cached_path_root: dropbox.common.PathRoot | None = None
        self._ns_detected: bool = False

    # ── OAuth2 Flows ──────────────────────────────────────────────

    def start_pkce_flow(self) -> str:
        """Start OAuth2 PKCE flow. Returns the authorization URL."""
        self._flow = DropboxOAuth2FlowNoRedirect(
            consumer_key=self._app_key,
            use_pkce=True,
            token_access_type="offline",
        )
        return self._flow.start()

    def start_auth_code_flow(self) -> str:
        """Start OAuth2 Authorization Code flow. Returns the authorization URL."""
        app_secret = get_app_secret()
        self._flow = DropboxOAuth2FlowNoRedirect(
            consumer_key=self._app_key,
            consumer_secret=app_secret or None,
            use_pkce=not bool(app_secret),
            token_access_type="offline",
        )
        return self._flow.start()

    def finish_flow(self, auth_code: str) -> AuthToken:
        """Complete the OAuth2 flow with the authorization code.

        Returns the AuthToken with access and refresh tokens.
        """
        if self._flow is None:
            raise AuthenticationError(
                "No OAuth2 flow in progress. Call start_pkce_flow() or start_auth_code_flow() first.",
                code="AUTH_REQUIRED",
            )
        result = self._flow.finish(auth_code.strip())
        # SDK returns expires_at as a datetime object (or None)
        if result.expires_at and isinstance(result.expires_at, datetime):
            expires_at = result.expires_at.timestamp()
        elif result.expires_at:
            expires_at = float(result.expires_at)
        else:
            expires_at = time.time() + 14400  # default 4 hours
        token = AuthToken(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_at=expires_at,
            account_id=result.account_id,
            uid=getattr(result, "user_id", None),
        )
        return token

    # ── Token Persistence ─────────────────────────────────────────

    def save_token(self, token: AuthToken) -> None:
        """Persist token to disk with atomic write and 0600 permissions."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        # Set directory permissions to 0700
        os.chmod(self._config_dir, 0o700)

        data = json.dumps(token.to_dict(), indent=2)

        # Atomic write: write to temp file, then rename
        fd, tmp_path = tempfile.mkstemp(dir=self._config_dir, prefix=".tokens_", suffix=".tmp")
        try:
            os.write(fd, data.encode())
            os.close(fd)
            os.chmod(tmp_path, 0o600)
            os.rename(tmp_path, self._token_path)
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            if os.path.exists(tmp_path):
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

    # ── Dropbox Client ────────────────────────────────────────────

    def get_client(self, *, timeout: int | None = None) -> dropbox.Dropbox:
        """Get a Dropbox SDK client using stored token (with auto-refresh).

        For team accounts, automatically sets path_root to the team root
        namespace so all files (including team members' shared docs) are
        accessible. Namespace info is persisted in the token file to avoid
        an API call on every invocation.

        Args:
            timeout: Request timeout in seconds. None uses SDK default (100s).

        Raises:
            AuthenticationError: If no token is stored.
        """
        token = self.load_token()
        if token is None:
            raise AuthenticationError(
                "Not authenticated. Run 'paper auth login' first.",
                code="AUTH_REQUIRED",
            )
        kwargs: dict = {
            "oauth2_access_token": token.access_token,
            "oauth2_refresh_token": token.refresh_token,
            "app_key": self._app_key,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        dbx = dropbox.Dropbox(**kwargs)

        if not self._ns_detected:
            # Try cached namespace from token file first (no API call)
            if token.root_namespace_id and token.home_namespace_id:
                if token.root_namespace_id != token.home_namespace_id:
                    self._cached_path_root = dropbox.common.PathRoot.root(token.root_namespace_id)
                self._ns_detected = True
            else:
                # First-time detection — use a short timeout to avoid blocking CLI
                try:
                    detect_dbx = dropbox.Dropbox(
                        oauth2_access_token=token.access_token,
                        oauth2_refresh_token=token.refresh_token,
                        app_key=self._app_key,
                        timeout=10,
                    )
                    account = detect_dbx.users_get_current_account()
                    root_info = account.root_info
                    root_ns = root_info.root_namespace_id
                    home_ns = root_info.home_namespace_id
                    if root_ns != home_ns:
                        self._cached_path_root = dropbox.common.PathRoot.root(root_ns)
                    # Persist namespace info + refreshed token
                    self._persist_refreshed_token(
                        detect_dbx, token, root_ns=root_ns, home_ns=home_ns
                    )
                except Exception:
                    pass
                self._ns_detected = True

        if self._cached_path_root is not None:
            dbx = dbx.with_path_root(self._cached_path_root)
        return dbx

    def _persist_refreshed_token(
        self,
        dbx: dropbox.Dropbox,
        original: AuthToken,
        *,
        root_ns: str | None = None,
        home_ns: str | None = None,
    ) -> None:
        """Persist refreshed access token and/or namespace info."""
        new_access = getattr(dbx, "_oauth2_access_token", None)
        access_changed = new_access and new_access != original.access_token
        ns_changed = root_ns and root_ns != original.root_namespace_id

        if not access_changed and not ns_changed:
            return

        new_expiry = getattr(dbx, "_oauth2_access_token_expiration", None)
        expires_at = (
            new_expiry.timestamp() if (new_expiry and access_changed) else original.expires_at
        )
        self.save_token(
            AuthToken(
                access_token=new_access
                if (access_changed and new_access)
                else original.access_token,
                refresh_token=original.refresh_token,
                account_id=original.account_id,
                expires_at=expires_at,
                uid=original.uid,
                token_type=original.token_type,
                root_namespace_id=root_ns or original.root_namespace_id,
                home_namespace_id=home_ns or original.home_namespace_id,
            )
        )
