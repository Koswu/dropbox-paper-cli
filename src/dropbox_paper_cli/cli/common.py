"""Shared CLI helpers: service factories, formatter, error handling."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import typer

from dropbox_paper_cli.lib.errors import AppError
from dropbox_paper_cli.lib.output import OutputFormatter
from dropbox_paper_cli.services.auth_service import AuthService
from dropbox_paper_cli.services.dropbox_service import DropboxService


def get_formatter(ctx: typer.Context) -> OutputFormatter:
    """Build an OutputFormatter from the root context's global flags."""
    current = ctx
    while current.parent is not None:
        current = current.parent
    json_mode = current.params.get("json_output", False)
    verbose = current.params.get("verbose", False)
    return OutputFormatter(json_mode=json_mode, verbose=verbose)


def get_auth_service() -> AuthService:
    """Get the default AuthService instance."""
    return AuthService()


def get_dropbox_service() -> DropboxService:
    """Get a DropboxService with an authenticated client."""
    svc = AuthService()
    client = svc.get_client()
    return DropboxService(client=client)


@contextmanager
def safe_command(fmt: OutputFormatter) -> Generator[None]:
    """Standard error handler for CLI commands.

    Handles AppError (with per-error exit codes), ValueError (URL parse
    errors, exit 4), and unexpected exceptions (exit 1).
    """
    try:
        yield
    except typer.Exit:
        raise
    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None
