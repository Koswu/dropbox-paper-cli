"""Auth CLI commands: login, logout, status."""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from dropbox_paper_cli.lib.config import TOKEN_PATH
from dropbox_paper_cli.lib.errors import AppError
from dropbox_paper_cli.lib.output import OutputFormatter
from dropbox_paper_cli.services.auth_service import AuthService

auth_app = typer.Typer(name="auth", help="Authentication commands.", no_args_is_help=True)


def _get_auth_service() -> AuthService:
    """Get the default AuthService instance. Patched in tests."""
    return AuthService()


def _get_formatter(ctx: typer.Context) -> OutputFormatter:
    """Build an OutputFormatter from the root context's global flags."""
    # Walk up the context chain to find global options set on the root app callback
    current = ctx
    while current.parent is not None:
        current = current.parent
    json_mode = current.params.get("json_output", False)
    verbose = current.params.get("verbose", False)
    return OutputFormatter(json_mode=json_mode, verbose=verbose)


@auth_app.command()
def login(
    ctx: typer.Context,
    flow: str = typer.Option("pkce", "--flow", help="OAuth2 flow type: pkce or code"),
) -> None:
    """Initiate OAuth2 authentication flow."""
    fmt = _get_formatter(ctx)
    svc = _get_auth_service()

    try:
        # Start the appropriate flow
        url = svc.start_auth_code_flow() if flow == "code" else svc.start_pkce_flow()

        fmt.verbose(f"Starting {flow} OAuth2 flow")

        if not fmt.json_mode:
            typer.echo("Opening browser for Dropbox authorization...")
            typer.echo(f"Authorization URL: {url}")
            typer.echo("")

        # Prompt for auth code
        auth_code = typer.prompt("Paste the authorization code")

        # Complete the flow
        token = svc.finish_flow(auth_code)
        svc.save_token(token)

        # Get user info
        client = svc.get_client()
        account = client.users_get_current_account()

        if fmt.json_mode:
            fmt.success(
                {
                    "status": "authenticated",
                    "account_id": token.account_id,
                    "display_name": account.name.display_name,
                    "email": account.email,
                    "token_path": str(TOKEN_PATH),
                }
            )
        else:
            typer.echo("")
            typer.echo(f"✓ Authenticated as {account.name.display_name} ({account.email})")
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

    try:
        client = svc.get_client()
        account = client.users_get_current_account()

        # Reload token — get_client() may have persisted a refreshed access token
        token = svc.load_token() or token
        expires_str = datetime.fromtimestamp(token.expires_at, tz=UTC).isoformat()

        if fmt.json_mode:
            fmt.success(
                {
                    "authenticated": True,
                    "account_id": token.account_id,
                    "display_name": account.name.display_name,
                    "email": account.email,
                    "expires_at": expires_str,
                }
            )
        else:
            typer.echo(f"Authenticated as {account.name.display_name} ({account.email})")
            typer.echo(f"Account ID: {token.account_id}")
            typer.echo(f"Token expires: {expires_str}")

    except Exception:
        # Token exists but can't connect — show what we have
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
