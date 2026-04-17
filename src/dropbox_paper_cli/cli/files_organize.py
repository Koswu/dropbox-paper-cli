"""Organize commands: create-folder, move, copy, delete."""

from __future__ import annotations

import typer

# Runtime attribute lookup so test mocks on files._get_dropbox_service work.
from dropbox_paper_cli.cli import files as _files
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.cli.common import safe_command


@_files.files_app.command("create-folder")
def create_folder_cmd(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Path for the new folder"),
) -> None:
    """Create a new folder."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):
        svc = _files._get_dropbox_service()
        item = svc.create_folder(path)

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


@_files.files_app.command()
def move(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source file ID, path, or URL"),
    destination: str = typer.Argument(..., help="Destination path"),
) -> None:
    """Move a file or folder to a new location."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):
        svc = _files._get_dropbox_service()
        resolved_src = _files._resolve(source, svc)
        item = svc.move_item(resolved_src, destination)

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


@_files.files_app.command()
def copy(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source file ID, path, or URL"),
    destination: str = typer.Argument(..., help="Destination path"),
) -> None:
    """Copy a file or folder to a new location."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):
        svc = _files._get_dropbox_service()
        resolved_src = _files._resolve(source, svc)
        item = svc.copy_item(resolved_src, destination)

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


@_files.files_app.command()
def delete(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or URL"),
) -> None:
    """Delete a file or folder."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):
        svc = _files._get_dropbox_service()
        resolved = _files._resolve(target, svc)
        item = svc.delete_item(resolved)

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
