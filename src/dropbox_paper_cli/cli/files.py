"""Files CLI commands: list, metadata, link, read, create, write, create-folder, move, copy, delete."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

import typer

from dropbox_paper_cli.cli.common import get_dropbox_service as _get_dropbox_service
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.lib.errors import AppError
from dropbox_paper_cli.lib.url_parser import is_dropbox_url, resolve_target
from dropbox_paper_cli.services.dropbox_service import DropboxService


class ImportFormat(StrEnum):
    """Supported import formats for Paper documents."""

    markdown = "markdown"
    html = "html"
    plain_text = "plain_text"


class UpdatePolicy(StrEnum):
    """Supported update policies for Paper documents."""

    overwrite = "overwrite"
    update = "update"
    prepend = "prepend"
    append = "append"


files_app = typer.Typer(name="files", help="File and folder operations.", no_args_is_help=True)


def _resolve(target: str, svc: DropboxService) -> str:
    """Resolve target — if it's a URL, use SDK to get the real ID."""
    resolved = resolve_target(target)
    if is_dropbox_url(resolved):
        return svc.resolve_shared_link_url(resolved)
    return resolved


# ── Browse Commands (US2) ─────────────────────────────────────────


@files_app.command("list")
def list_cmd(
    ctx: typer.Context,
    path: str = typer.Argument("", help="Dropbox path to list (default: root)"),
    recursive: bool = typer.Option(False, "--recursive", help="List all items recursively"),
) -> None:
    """List files and folders at a Dropbox path."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
        items = svc.list_folder(path, recursive=recursive)

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
                            "modified": str(item.server_modified) if item.server_modified else None,
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

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


@files_app.command()
def metadata(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or Dropbox Paper URL"),
) -> None:
    """Get detailed metadata for a specific file or folder."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
        resolved = _resolve(target, svc)
        item = svc.get_metadata(resolved)

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

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


@files_app.command()
def link(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or Dropbox Paper URL"),
) -> None:
    """Get or create a sharing link for a file."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
        resolved = _resolve(target, svc)
        result = svc.get_or_create_sharing_link(resolved)

        if fmt.json_mode:
            fmt.success(result)
        else:
            typer.echo(result["url"])

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


# ── Organize Commands (US3) ───────────────────────────────────────


@files_app.command("create-folder")
def create_folder_cmd(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Path for the new folder"),
) -> None:
    """Create a new folder."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
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

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


@files_app.command()
def move(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source file ID, path, or URL"),
    destination: str = typer.Argument(..., help="Destination path"),
) -> None:
    """Move a file or folder to a new location."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
        resolved_src = _resolve(source, svc)
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

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


@files_app.command()
def copy(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source file ID, path, or URL"),
    destination: str = typer.Argument(..., help="Destination path"),
) -> None:
    """Copy a file or folder to a new location."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
        resolved_src = _resolve(source, svc)
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

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


@files_app.command()
def delete(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or URL"),
) -> None:
    """Delete a file or folder."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
        resolved = _resolve(target, svc)
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

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


# ── Read Command (US4) ────────────────────────────────────────────


@files_app.command()
def read(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or Dropbox Paper URL"),
) -> None:
    """Read and output Paper document content as Markdown."""
    fmt = _get_formatter(ctx)
    try:
        svc = _get_dropbox_service()
        resolved = _resolve(target, svc)

        # Get metadata for name/path info
        item = svc.get_metadata(resolved)
        content = svc.export_paper_content(resolved)

        if fmt.json_mode:
            fmt.success(
                {
                    "id": item.id,
                    "name": item.name,
                    "path": item.path_display,
                    "content": content,
                    "format": "markdown",
                }
            )
        else:
            typer.echo(content, nl=False)

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


# ── Write Commands ────────────────────────────────────────────────


def _read_content(file: str | None) -> bytes:
    """Read content from a local file path or stdin.

    Raises typer.Exit if stdin is a TTY and no file is given.
    """
    if file:
        return Path(file).read_bytes()
    if sys.stdin.isatty():
        typer.echo(
            "Error: no input provided. Pipe content via stdin or use --file/-f.",
            err=True,
        )
        raise typer.Exit(code=4)
    return sys.stdin.buffer.read()


@files_app.command()
def create(
    ctx: typer.Context,
    path: str = typer.Argument(
        ..., help="Dropbox path for the new Paper document (must end with .paper)"
    ),
    file: str | None = typer.Option(
        None, "--file", "-f", help="Read content from a local file (default: stdin)"
    ),
    import_format: ImportFormat = typer.Option(  # noqa: B008
        ImportFormat.markdown, "--format", help="Import format"
    ),
) -> None:
    """Create a new Paper document from Markdown, HTML, or plain text."""
    fmt = _get_formatter(ctx)
    try:
        content = _read_content(file)
        svc = _get_dropbox_service()
        result = svc.create_paper_doc(path, content, import_format=import_format.value)

        if fmt.json_mode:
            fmt.success(
                {
                    "status": "created",
                    "url": result.url,
                    "path": result.result_path,
                    "file_id": result.file_id,
                    "paper_revision": result.paper_revision,
                }
            )
        else:
            typer.echo("✓ Created Paper document")
            typer.echo(f"  Path: {result.result_path}")
            typer.echo(f"  URL:  {result.url}")
            typer.echo(f"  ID:   {result.file_id}")

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None


@files_app.command()
def write(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or Dropbox Paper URL"),
    file: str | None = typer.Option(
        None, "--file", "-f", help="Read content from a local file (default: stdin)"
    ),
    import_format: ImportFormat = typer.Option(  # noqa: B008
        ImportFormat.markdown, "--format", help="Import format"
    ),
    policy: UpdatePolicy = typer.Option(  # noqa: B008
        UpdatePolicy.overwrite, "--policy", help="Update policy"
    ),
    revision: int | None = typer.Option(
        None, "--revision", help="Paper revision (required for --policy update)"
    ),
) -> None:
    """Update an existing Paper document's content."""
    fmt = _get_formatter(ctx)
    try:
        content = _read_content(file)
        svc = _get_dropbox_service()
        resolved = _resolve(target, svc)
        result = svc.update_paper_doc(
            resolved,
            content,
            import_format=import_format.value,
            policy=policy.value,
            paper_revision=revision,
        )

        if fmt.json_mode:
            fmt.success(
                {
                    "status": "updated",
                    "target": resolved,
                    "policy": policy.value,
                    "paper_revision": result.paper_revision,
                }
            )
        else:
            typer.echo("✓ Updated Paper document")
            typer.echo(f"  Target:   {resolved}")
            typer.echo(f"  Policy:   {policy.value}")
            typer.echo(f"  Revision: {result.paper_revision}")

    except AppError as e:
        fmt.error(str(e), code=e.code)
        raise typer.Exit(code=e.exit_code) from None
    except ValueError as e:
        fmt.error(str(e), code="URL_PARSE_ERROR")
        raise typer.Exit(code=4) from None
    except Exception as e:
        fmt.error(str(e), code="GENERAL_FAILURE")
        raise typer.Exit(code=1) from None
