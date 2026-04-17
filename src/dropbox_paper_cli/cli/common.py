"""Shared CLI helpers: service factories, formatter, error handling."""

from __future__ import annotations

import typer

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
