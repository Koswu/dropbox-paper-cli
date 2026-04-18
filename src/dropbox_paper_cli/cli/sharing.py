"""Sharing CLI commands: info."""

from __future__ import annotations

import typer

from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.cli.common import run_with_client, safe_command
from dropbox_paper_cli.lib.url_parser import is_dropbox_url, resolve_target
from dropbox_paper_cli.services.dropbox_service import DropboxService
from dropbox_paper_cli.services.sharing_service import SharingService

sharing_app = typer.Typer(name="sharing", help="Sharing information.", no_args_is_help=True)


@sharing_app.command()
def info(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Folder ID, path, or URL"),
) -> None:
    """Get sharing information for a shared folder."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Getting sharing info for {target!r}")
            dbx_svc = DropboxService(client=client)
            share_svc = SharingService(client=client)

            resolved = resolve_target(target)
            if is_dropbox_url(resolved):
                fmt.verbose(f"Resolving shared link URL: {resolved!r}")
                resolved = await dbx_svc.resolve_shared_link_url(resolved)
            fmt.verbose(f"Resolved to {resolved!r}")

            shared_folder_id = await dbx_svc.get_shared_folder_id(resolved)
            if shared_folder_id is None:
                from dropbox_paper_cli.lib.errors import ValidationError

                raise ValidationError(f"Target is not a shared folder: {resolved}")

            sharing_info = await share_svc.get_sharing_info(shared_folder_id)

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

        run_with_client(_run)
