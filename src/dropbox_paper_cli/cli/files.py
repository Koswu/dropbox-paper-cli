"""Files CLI: orchestrator that creates files_app and registers submodule commands."""

from __future__ import annotations

import typer

from dropbox_paper_cli.lib.url_parser import is_dropbox_url, resolve_target
from dropbox_paper_cli.services.dropbox_service import DropboxService

files_app = typer.Typer(name="files", help="File and folder operations.", no_args_is_help=True)


async def _resolve(target: str, svc: DropboxService) -> str:
    """Resolve target — if it's a URL, use API to get the real ID."""
    resolved = resolve_target(target)
    if is_dropbox_url(resolved):
        return await svc.resolve_shared_link_url(resolved)
    return resolved


# Import submodules to register their commands on files_app.
# Must be at module bottom to avoid circular imports.
from dropbox_paper_cli.cli import files_browse as _files_browse  # noqa: E402, F401
from dropbox_paper_cli.cli import files_content as _files_content  # noqa: E402, F401
from dropbox_paper_cli.cli import files_organize as _files_organize  # noqa: E402, F401
