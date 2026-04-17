"""CLI commands for app configuration."""

from __future__ import annotations

import json

import typer

from dropbox_paper_cli.lib.config import APP_CONFIG_PATH, CONFIG_DIR

config_app = typer.Typer(no_args_is_help=True)


@config_app.command("set")
def config_set(
    app_key: str = typer.Option(None, "--app-key", help="Dropbox app key"),
    app_secret: str = typer.Option(None, "--app-secret", help="Dropbox app secret"),
) -> None:
    """Set Dropbox app credentials."""
    if app_key is None and app_secret is None:
        typer.echo("Provide at least one of --app-key or --app-secret.", err=True)
        raise typer.Exit(1)

    cfg: dict = {}
    if APP_CONFIG_PATH.exists():
        try:
            cfg = json.loads(APP_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            cfg = {}

    if app_key is not None:
        cfg["app_key"] = app_key
    if app_secret is not None:
        cfg["app_secret"] = app_secret

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    APP_CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")

    typer.echo(f"Config saved to {APP_CONFIG_PATH}")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    if not APP_CONFIG_PATH.exists():
        typer.echo(f"No config file found at {APP_CONFIG_PATH}")
        typer.echo("Run: paper config set --app-key YOUR_KEY")
        raise typer.Exit(1)

    try:
        cfg = json.loads(APP_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"Error reading config: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(f"Config file: {APP_CONFIG_PATH}")
    if "app_key" in cfg:
        typer.echo(f"  app_key:    {cfg['app_key']}")
    if "app_secret" in cfg:
        masked = cfg["app_secret"][:4] + "****" if len(cfg["app_secret"]) > 4 else "****"
        typer.echo(f"  app_secret: {masked}")


@config_app.command("path")
def config_path() -> None:
    """Show config file path."""
    typer.echo(str(APP_CONFIG_PATH))
