"""Sharing CLI commands: info."""

from __future__ import annotations

import typer

from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.lib.errors import AppError
from dropbox_paper_cli.lib.url_parser import is_dropbox_url, resolve_target
from dropbox_paper_cli.services.auth_service import AuthService
from dropbox_paper_cli.services.dropbox_service import DropboxService
from dropbox_paper_cli.services.sharing_service import SharingService

sharing_app = typer.Typer(name="sharing", help="Sharing information.", no_args_is_help=True)


def _get_services() -> tuple[DropboxService, SharingService]:
    """Get DropboxService and SharingService with an authenticated client. Patched in tests."""
    svc = AuthService()
    client = svc.get_client()
    return DropboxService(client=client), SharingService(client=client)


@sharing_app.command()
def info(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Folder ID, path, or URL"),
) -> None:
    """Get sharing information for a shared folder."""
    fmt = _get_formatter(ctx)
    try:
        dbx_svc, share_svc = _get_services()
        resolved = resolve_target(target)
        if is_dropbox_url(resolved):
            resolved = dbx_svc.resolve_shared_link_url(resolved)

        # Get the shared_folder_id from folder metadata
        shared_folder_id = dbx_svc.get_shared_folder_id(resolved)
        if shared_folder_id is None:
            from dropbox_paper_cli.lib.errors import ValidationError

            raise ValidationError(f"Target is not a shared folder: {resolved}")

        sharing_info = share_svc.get_sharing_info(shared_folder_id)

        if fmt.json_mode:
            fmt.success(
                {
                    "shared_folder_id": sharing_info.shared_folder_id,
                    "name": sharing_info.name,
                    "members": [
                        {
                            "display_name": m.display_name,
                            "email": m.email,
                            "access_type": m.access_type,
                        }
                        for m in sharing_info.members
                    ],
                }
            )
        else:
            typer.echo(f"Shared Folder: {sharing_info.name}")
            typer.echo(f"Folder ID:     {sharing_info.shared_folder_id}")
            typer.echo("")
            typer.echo("Members:")
            for m in sharing_info.members:
                typer.echo(
                    f"  {m.display_name} ({m.email})  {' ' * max(0, 25 - len(m.display_name) - len(m.email))}{m.access_type}"
                )

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None
