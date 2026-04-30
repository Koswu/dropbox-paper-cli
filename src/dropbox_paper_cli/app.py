"""Main Typer application assembly with global options."""

from __future__ import annotations

import logging
import os

import typer

from dropbox_paper_cli import __version__
from dropbox_paper_cli.cli.auth import auth_app
from dropbox_paper_cli.cli.cache import cache_app
from dropbox_paper_cli.cli.config import config_app
from dropbox_paper_cli.cli.files import files_app
from dropbox_paper_cli.cli.sharing import sharing_app


def _sanitize_no_proxy() -> None:
    # httpx/urllib don't accept IPv6 (especially CIDR like `::ffff:0:0:0:0/1`)
    # in no_proxy and crash with `Invalid port: ...`. Some macOS proxy clients
    # write such entries by default; strip anything containing `::`.
    for key in ("no_proxy", "NO_PROXY"):
        raw = os.environ.get(key)
        if not raw:
            continue
        entries = [e.strip() for e in raw.split(",")]
        kept = [e for e in entries if e and "::" not in e]
        if len(kept) == len([e for e in entries if e]):
            continue
        if kept:
            os.environ[key] = ",".join(kept)
        else:
            os.environ.pop(key, None)


_sanitize_no_proxy()


app = typer.Typer(
    name="paper",
    help="Dropbox Paper CLI — manage Paper documents from the terminal.",
    no_args_is_help=True,
)

# Register command groups
app.add_typer(auth_app, name="auth", help="Authentication commands.")
app.add_typer(config_app, name="config", help="App configuration.")
app.add_typer(files_app, name="files", help="File and folder operations.")
app.add_typer(cache_app, name="cache", help="Local metadata cache and search.")
app.add_typer(sharing_app, name="sharing", help="Sharing information.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"paper {__version__}")
        raise typer.Exit()


def _configure_logging(verbose: bool) -> None:
    """Configure logging based on --verbose flag and PAPER_LOG_LEVEL env var.

    Priority: --verbose flag sets DEBUG. Otherwise, PAPER_LOG_LEVEL env var is
    used (e.g. DEBUG, INFO, WARNING). Default is WARNING (suppress most output).
    """
    level_name = os.environ.get("PAPER_LOG_LEVEL", "WARNING").upper()
    if verbose:
        level_name = "DEBUG"

    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # Ensure our library loggers respect the level
    logging.getLogger("dropbox_paper_cli").setLevel(level)


@app.callback()
def main(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON to stdout"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose diagnostics to stderr"),
    version: bool = typer.Option(
        False, "--version", help="Show version and exit", callback=_version_callback, is_eager=True
    ),
) -> None:
    """Dropbox Paper CLI — manage Paper documents from the terminal."""
    _configure_logging(verbose)
