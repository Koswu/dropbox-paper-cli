"""Content commands: read, create, write."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

import typer

# Runtime attribute lookup so test mocks on files._get_dropbox_service work.
from dropbox_paper_cli.cli import files as _files
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.cli.common import safe_command


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


@_files.files_app.command()
def read(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File ID, path, or Dropbox Paper URL"),
) -> None:
    """Read and output Paper document content as Markdown."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt):
        fmt.verbose(f"Reading document {target!r}")
        svc = _files._get_dropbox_service()
        resolved = _files._resolve(target, svc)
        fmt.verbose(f"Resolved to {resolved!r}")

        # Get metadata for name/path info
        item = svc.get_metadata(resolved)
        fmt.verbose(f"Exporting content for {item.name!r}")
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


@_files.files_app.command()
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
    with safe_command(fmt):
        content = _read_content(file)
        fmt.verbose(
            f"Creating document at {path!r} format={import_format.value} ({len(content)} bytes)"
        )
        svc = _files._get_dropbox_service()
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


@_files.files_app.command()
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
    with safe_command(fmt):
        content = _read_content(file)
        fmt.verbose(
            f"Updating {target!r} format={import_format.value} policy={policy.value} ({len(content)} bytes)"
        )
        svc = _files._get_dropbox_service()
        resolved = _files._resolve(target, svc)
        fmt.verbose(f"Resolved to {resolved!r}")
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
