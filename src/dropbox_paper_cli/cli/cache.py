"""Cache CLI commands: sync and search."""

from __future__ import annotations

import sys
from collections.abc import Callable

import typer

from dropbox_paper_cli.cli.common import get_auth_service as _get_auth_service
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.cli.common import safe_command
from dropbox_paper_cli.db.connection import CacheDatabase
from dropbox_paper_cli.models.cache import SyncResult
from dropbox_paper_cli.services.cache_service import CacheService

cache_app = typer.Typer(name="cache", help="Local metadata cache and search.", no_args_is_help=True)


def _get_cache_service(db: CacheDatabase) -> CacheService:
    """Get a CacheService with an authenticated client. Patched in tests."""
    svc = _get_auth_service()
    client = svc.get_client()

    def client_factory():
        return svc.get_client()

    return CacheService(conn=db.conn, client=client, client_factory=client_factory)


def _make_progress_callback(
    is_tty: bool,
) -> tuple[Callable[[SyncResult], None], Callable[[], None]]:
    """Return (on_progress callback, finalizer).

    Progress is written to stderr only when connected to a TTY.
    Finalizer clears the progress line.
    """
    last_reported = [0]

    def on_progress(r: SyncResult) -> None:
        total = r.added + r.updated
        if not is_tty:
            return
        if total - last_reported[0] >= 100 or total == 0:
            sys.stderr.write(f"\r  ⏳ {total:,} items processed...")
            sys.stderr.flush()
            last_reported[0] = total

    def finalize() -> None:
        if is_tty and last_reported[0] > 0:
            sys.stderr.write("\r" + " " * 40 + "\r")
            sys.stderr.flush()

    return on_progress, finalize


@cache_app.command()
def sync(
    ctx: typer.Context,
    full: bool = typer.Option(False, "--full", help="Force a full resync (ignore saved cursor)"),
    path: str = typer.Option("", "--path", help="Dropbox path to sync (default: root)"),
    concurrency: int = typer.Option(20, "--concurrency", "-c", help="Max concurrent API requests"),
) -> None:
    """Sync the Dropbox directory tree metadata to the local SQLite cache."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt), CacheDatabase() as db:
        svc = _get_cache_service(db)

        is_tty = sys.stderr.isatty()
        on_progress, finalize = _make_progress_callback(is_tty and not fmt.json_mode)

        if not fmt.json_mode:
            typer.echo("Syncing metadata...")

        result = svc.sync(
            force_full=full,
            path=path,
            concurrency=concurrency,
            on_progress=on_progress,
        )
        finalize()

        if fmt.json_mode:
            fmt.success(
                {
                    "status": "synced",
                    "added": result.added,
                    "updated": result.updated,
                    "removed": result.removed,
                    "total": result.total,
                    "duration_seconds": result.duration_seconds,
                    "sync_type": result.sync_type,
                }
            )
        else:
            typer.echo(f"  Added:   {result.added} items")
            typer.echo(f"  Updated: {result.updated} items")
            typer.echo(f"  Removed: {result.removed} items")
            typer.echo(f"  Total:   {result.total:,} items in cache")
            typer.echo("")
            typer.echo(f"✓ Sync complete ({result.duration_seconds}s)")


@cache_app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search keyword(s)"),
    item_type: str | None = typer.Option(
        None, "--type", help="Filter by item type: file or folder"
    ),
    limit: int = typer.Option(50, "--limit", help="Maximum results to return"),
) -> None:
    """Search file and folder names in the local cache by keyword."""
    fmt = _get_formatter(ctx)
    with safe_command(fmt), CacheDatabase() as db:
        # Search doesn't need a Dropbox client — just use the DB directly
        from dropbox_paper_cli.services.cache_service import CacheService

        # Create a service with a dummy client for search-only
        svc = CacheService(conn=db.conn, client=None)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        results = svc.search(query, item_type=item_type, limit=limit)

        if fmt.json_mode:
            fmt.success(
                {
                    "query": query,
                    "results": [
                        {
                            "id": r.id,
                            "name": r.name,
                            "path": r.path_display,
                            "type": r.item_type,
                        }
                        for r in results
                    ],
                    "count": len(results),
                }
            )
        else:
            if not results:
                typer.echo(f'No results for "{query}".')
                return
            typer.echo(f'Found {len(results)} results for "{query}":')
            typer.echo("")
            for r in results:
                tag = {"paper": "📝", "folder": "📁", "file": "📄"}.get(r.item_type, "📄")
                name = f"{r.name}/" if r.is_dir else r.name
                typer.echo(f"{tag} [{r.item_type:<6s}] {name:<30s} {r.path_display}")


@cache_app.command()
def isearch(
    ctx: typer.Context,
    query: str = typer.Argument("", help="Optional initial search query"),
) -> None:
    """Interactive TUI search over the local metadata cache.

    Key bindings:
      Enter   Move focus to results table
      F2      Get sharing link for selected item
      F3      Open selected item in browser
      F4      Preview Paper document content
      Escape  Quit
    """
    fmt = _get_formatter(ctx)
    if fmt.json_mode:
        fmt.error("Interactive search does not support --json mode", code="INVALID_ARGUMENT")
        raise typer.Exit(code=1) from None

    from dropbox_paper_cli.tui.search import run_search_tui  # noqa: PLC0415

    run_search_tui(initial_query=query)
