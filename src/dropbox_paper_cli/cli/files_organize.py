"""Organize commands: create-folder, move, copy, delete."""

from __future__ import annotations

import typer

from dropbox_paper_cli.cli import files as _files
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.cli.common import run_with_client, safe_command
from dropbox_paper_cli.services.dropbox_service import DropboxService


@_files.files_app.command("create-folder")
def create_folder_cmd(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Path for the new folder"),
) -> None:
    """Create a new folder."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Creating folder at {path!r}")
            svc = DropboxService(client=client)
            item = await svc.create_folder(path)

            if fmt.json_mode:
                fmt.success(
                    {
                        "status": "created",
                        "name": item.name,
                        "path": item.path_display,
                        "id": item.id,
                        "type": "folder",
                    }
                )
            else:
                typer.echo(f'✓ Created folder "{item.name}"')
                typer.echo(f"  Path: {item.path_display}")
                typer.echo(f"  ID:   {item.id}")

        run_with_client(_run)


@_files.files_app.command()
def move(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source file ID, path, or URL"),
    destination: str = typer.Argument(..., help="Destination path"),
) -> None:
    """Move a file or folder to a new location."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Moving {source!r} → {destination!r}")
            svc = DropboxService(client=client)
            resolved_src = await _files._resolve(source, svc)
            fmt.verbose(f"Source resolved to {resolved_src!r}")
            item = await svc.move_item(resolved_src, destination)

            if fmt.json_mode:
                fmt.success(
                    {
                        "status": "moved",
                        "name": item.name,
                        "from": resolved_src,
                        "to": item.path_display,
                        "id": item.id,
                    }
                )
            else:
                typer.echo(f'✓ Moved "{item.name}"')
                typer.echo(f"  From: {resolved_src}")
                typer.echo(f"  To:   {item.path_display}")

        run_with_client(_run)


@_files.files_app.command()
def copy(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source file ID, path, or URL"),
    destination: str = typer.Argument(..., help="Destination path"),
) -> None:
    """Copy a file or folder to a new location."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Copying {source!r} → {destination!r}")
            svc = DropboxService(client=client)
            resolved_src = await _files._resolve(source, svc)
            fmt.verbose(f"Source resolved to {resolved_src!r}")
            item = await svc.copy_item(resolved_src, destination)

            if fmt.json_mode:
                fmt.success(
                    {
                        "status": "copied",
                        "name": item.name,
                        "from": resolved_src,
                        "to": item.path_display,
                        "new_id": item.id,
                    }
                )
            else:
                typer.echo(f'✓ Copied "{item.name}"')
                typer.echo(f"  To: {item.path_display}")
                typer.echo(f"  New ID: {item.id}")

        run_with_client(_run)


@_files.files_app.command()
def delete(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or URL"),
) -> None:
    """Delete a file or folder."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Deleting {target!r}")
            svc = DropboxService(client=client)
            resolved = await _files._resolve(target, svc)
            fmt.verbose(f"Resolved to {resolved!r}")
            item = await svc.delete_item(resolved)

            if fmt.json_mode:
                fmt.success(
                    {
                        "status": "deleted",
                        "name": item.name,
                        "path": item.path_display,
                        "id": item.id,
                    }
                )
            else:
                typer.echo(f'✓ Deleted "{item.name}"')

        run_with_client(_run)
