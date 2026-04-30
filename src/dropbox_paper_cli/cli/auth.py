"""Auth CLI commands: login, logout, status."""

from __future__ import annotations

import asyncio
import contextlib
import threading
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import typer

from dropbox_paper_cli.cli.common import get_auth_service as _get_auth_service
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.lib.config import TOKEN_PATH
from dropbox_paper_cli.lib.errors import AppError

auth_app = typer.Typer(name="auth", help="Authentication commands.", no_args_is_help=True)

LOOPBACK_PORT = 53682


def _capture_loopback_code(port: int, timeout: float = 300.0) -> tuple[str, str]:
    """Run a one-shot localhost HTTP server to capture the OAuth2 redirect.

    Returns (auth_code, redirect_uri). Raises AppError on timeout or error.
    """
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            if "code" in qs:
                received["code"] = qs["code"][0]
                body = b"<html><body><h2>Authorization complete.</h2>You can close this tab.</body></html>"
                self.send_response(200)
            elif "error" in qs:
                received["error"] = qs.get("error_description", qs["error"])[0]
                body = f"<html><body><h2>Authorization failed.</h2>{received['error']}</body></html>".encode()
                self.send_response(400)
            else:
                body = b"<html><body>Missing code parameter.</body></html>"
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args, **_kwargs) -> None:
            pass

    try:
        server = HTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise AppError(
            f"Failed to bind loopback port {port}: {exc}", code="AUTH_REQUIRED"
        ) from None

    actual_port = server.server_address[1]
    redirect_uri = f"http://localhost:{actual_port}/"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.start()
        try:
            while not deadline.is_set() and "code" not in received and "error" not in received:
                deadline.wait(0.2)
        finally:
            timer.cancel()
    finally:
        server.shutdown()
        server.server_close()

    if "error" in received:
        raise AppError(f"Authorization failed: {received['error']}", code="AUTH_REQUIRED")
    if "code" not in received:
        raise AppError("Timed out waiting for loopback redirect.", code="AUTH_REQUIRED")
    return received["code"], redirect_uri


@auth_app.command()
def login(
    ctx: typer.Context,
    flow: str = typer.Option("pkce", "--flow", help="OAuth2 flow type: pkce or code"),
    loopback: bool = typer.Option(
        False,
        "--loopback",
        help=f"Capture the auth code via a localhost redirect on port {LOOPBACK_PORT} "
        "(no manual paste). The redirect URI "
        f"http://localhost:{LOOPBACK_PORT}/ must be registered in your Dropbox app settings.",
    ),
) -> None:
    """Initiate OAuth2 authentication flow."""
    fmt = _get_formatter(ctx)
    svc = _get_auth_service()

    try:
        redirect_uri: str | None = None
        if loopback:
            redirect_uri = f"http://localhost:{LOOPBACK_PORT}/"

        # Start the appropriate flow
        if flow == "code":
            url = svc.start_auth_code_flow(redirect_uri=redirect_uri)
        else:
            url = svc.start_pkce_flow(redirect_uri=redirect_uri)

        fmt.verbose(f"Starting {flow} OAuth2 flow")
        if loopback:
            fmt.verbose(f"Loopback redirect URI: {redirect_uri}")

        if not fmt.json_mode:
            typer.echo("Opening browser for Dropbox authorization...")
            typer.echo(f"Authorization URL: {url}")
            typer.echo("")

        if loopback:
            with contextlib.suppress(Exception):
                webbrowser.open(url)
            if not fmt.json_mode:
                typer.echo(f"Waiting for redirect on {redirect_uri} ...")
            auth_code, _ = _capture_loopback_code(LOOPBACK_PORT)
        else:
            # Prompt for auth code
            auth_code = typer.prompt("Paste the authorization code")

        # Complete the flow (async)
        token = asyncio.run(svc.finish_flow(auth_code))
        svc.save_token(token)

        # Get user info via API
        account = asyncio.run(svc.get_account_info())

        if fmt.json_mode:
            fmt.success(
                {
                    "status": "authenticated",
                    "account_id": token.account_id,
                    "display_name": account["display_name"],
                    "email": account["email"],
                    "token_path": str(TOKEN_PATH),
                }
            )
        else:
            typer.echo("")
            typer.echo(f"✓ Authenticated as {account['display_name']} ({account['email']})")
            typer.echo(f"  Account ID: {token.account_id}")
            typer.echo(f"  Token stored at: {TOKEN_PATH}")

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except Exception as e:
        fmt.error(str(e), code="AUTH_REQUIRED")
        raise typer.Exit(code=2) from None


@auth_app.command()
def logout(ctx: typer.Context) -> None:
    """Clear stored credentials."""
    fmt = _get_formatter(ctx)
    svc = _get_auth_service()

    fmt.verbose("Removing stored credentials")
    svc.delete_token()

    if fmt.json_mode:
        fmt.success({"status": "logged_out"})
    else:
        typer.echo("✓ Credentials removed.")


@auth_app.command()
def status(ctx: typer.Context) -> None:
    """Check current authentication state."""
    fmt = _get_formatter(ctx)
    svc = _get_auth_service()

    token = svc.load_token()

    if token is None:
        if fmt.json_mode:
            fmt.success({"authenticated": False})
        else:
            typer.echo("Not authenticated. Run 'paper auth login' to connect.")
        return

    fmt.verbose("Token loaded from disk")
    fmt.verbose(f"  Account ID: {token.account_id}")
    fmt.verbose(f"  Token expired: {token.is_expired}")
    if token.root_namespace_id:
        fmt.verbose(
            f"  Cached namespace: root={token.root_namespace_id} home={token.home_namespace_id}"
        )
    else:
        fmt.verbose("  Namespace not cached (will detect on first API call)")

    try:
        fmt.verbose("Verifying token with Dropbox API...")
        account = asyncio.run(svc.get_account_info())
        fmt.verbose("API verification successful")

        # Reload token — the HTTP client may have refreshed it
        token = svc.load_token() or token
        expires_str = datetime.fromtimestamp(token.expires_at, tz=UTC).isoformat()

        if fmt.json_mode:
            fmt.success(
                {
                    "authenticated": True,
                    "account_id": token.account_id,
                    "display_name": account["display_name"],
                    "email": account["email"],
                    "expires_at": expires_str,
                }
            )
        else:
            typer.echo(f"Authenticated as {account['display_name']} ({account['email']})")
            typer.echo(f"Account ID: {token.account_id}")
            typer.echo(f"Token expires: {expires_str}")

    except Exception as exc:
        fmt.verbose(f"API verification failed: {exc}")
        if fmt.json_mode:
            fmt.success(
                {
                    "authenticated": True,
                    "account_id": token.account_id,
                    "display_name": None,
                    "email": None,
                    "expires_at": datetime.fromtimestamp(token.expires_at, tz=UTC).isoformat(),
                }
            )
        else:
            typer.echo(f"Authenticated (account: {token.account_id})")
            typer.echo("  Warning: Could not verify token with Dropbox API")
