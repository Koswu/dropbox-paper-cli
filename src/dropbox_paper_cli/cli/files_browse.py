"""Browse commands: list, metadata, link."""

from __future__ import annotations

import typer

from dropbox_paper_cli.cli import files as _files
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.cli.common import run_with_client, safe_command
from dropbox_paper_cli.services.dropbox_service import DropboxService


@_files.files_app.command("list")
def list_cmd(
    ctx: typer.Context,
    path: str = typer.Argument("", help="Dropbox path to list (default: root)"),
    recursive: bool = typer.Option(False, "--recursive", help="List all items recursively"),
) -> None:
    """List files and folders at a Dropbox path."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Listing path={path!r} recursive={recursive}")
            svc = DropboxService(client=client)
            items = await svc.list_folder(path, recursive=recursive)
            fmt.verbose(f"Got {len(items)} items")

            if fmt.json_mode:
                fmt.success(
                    {
                        "path": path,
                        "items": [
                            {
                                "id": item.id,
                                "name": item.name,
                                "path": item.path_display,
                                "type": item.type,
                                "modified": str(item.server_modified)
                                if item.server_modified
                                else None,
                                "size": item.size,
                            }
                            for item in items
                        ],
                    }
                )
            else:
                if not items:
                    typer.echo("(empty)")
                    return
                for item in items:
                    icon = "📁" if item.type == "folder" else "📄"
                    name = f"{item.name}/" if item.type == "folder" else item.name
                    modified = str(item.server_modified.date()) if item.server_modified else ""
                    size_str = ""
                    if item.size is not None:
                        if item.size >= 1024:
                            size_str = f"  {item.size / 1024:.1f} KB"
                        else:
                            size_str = f"  {item.size} B"
                    typer.echo(f"{icon} {name:<30s} {modified}{size_str}")

        run_with_client(_run)


@_files.files_app.command()
def metadata(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or Dropbox Paper URL"),
) -> None:
    """Get detailed metadata for a specific file or folder."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Getting metadata for {target!r}")
            svc = DropboxService(client=client)
            resolved = await _files._resolve(target, svc)
            fmt.verbose(f"Resolved to {resolved!r}")
            item = await svc.get_metadata(resolved)

            if fmt.json_mode:
                fmt.success(
                    {
                        "id": item.id,
                        "name": item.name,
                        "path": item.path_display,
                        "type": item.type,
                        "size": item.size,
                        "modified": str(item.server_modified) if item.server_modified else None,
                        "rev": item.rev,
                        "content_hash": item.content_hash,
                    }
                )
            else:
                typer.echo(f"Name:     {item.name}")
                typer.echo(f"Type:     {item.type}")
                typer.echo(f"Path:     {item.path_display}")
                typer.echo(f"ID:       {item.id}")
                if item.size is not None:
                    typer.echo(f"Size:     {item.size:,} bytes")
                if item.server_modified:
                    typer.echo(f"Modified: {item.server_modified}")
                if item.rev:
                    typer.echo(f"Rev:      {item.rev}")

        run_with_client(_run)


@_files.files_app.command()
def link(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or Dropbox Paper URL"),
) -> None:
    """Get or create a sharing link for a file."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):

        async def _run(client) -> None:
            fmt.verbose(f"Getting sharing link for {target!r}")
            svc = DropboxService(client=client)
            resolved = await _files._resolve(target, svc)
            fmt.verbose(f"Resolved to {resolved!r}")
            result = await svc.get_or_create_sharing_link(resolved)

            if fmt.json_mode:
                fmt.success(result)
            else:
                typer.echo(result["url"])

        run_with_client(_run)
