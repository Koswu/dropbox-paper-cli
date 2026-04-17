"""Main Typer application assembly with global options."""

from __future__ import annotations

import typer

from dropbox_paper_cli import __version__
from dropbox_paper_cli.cli.auth import auth_app
from dropbox_paper_cli.cli.cache import cache_app
from dropbox_paper_cli.cli.files import files_app
from dropbox_paper_cli.cli.sharing import sharing_app

app = typer.Typer(
    name="paper",
    help="Dropbox Paper CLI — manage Paper documents from the terminal.",
    no_args_is_help=True,
)

# Register command groups
app.add_typer(auth_app, name="auth", help="Authentication commands.")
app.add_typer(files_app, name="files", help="File and folder operations.")
app.add_typer(cache_app, name="cache", help="Local metadata cache and search.")
app.add_typer(sharing_app, name="sharing", help="Sharing information.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"paper {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON to stdout"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose diagnostics to stderr"),
    version: bool = typer.Option(
        False, "--version", help="Show version and exit", callback=_version_callback, is_eager=True
    ),
) -> None:
    """Dropbox Paper CLI — manage Paper documents from the terminal."""
