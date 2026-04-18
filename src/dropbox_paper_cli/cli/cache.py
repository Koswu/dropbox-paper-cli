"""Cache CLI commands: sync and search."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from dropbox_paper_cli.cli.common import get_auth_service as _get_auth_service
from dropbox_paper_cli.cli.common import get_formatter as _get_formatter
from dropbox_paper_cli.cli.common import safe_command
from dropbox_paper_cli.db.connection import CacheDatabase
from dropbox_paper_cli.services.cache_service import CacheService

if TYPE_CHECKING:
    from dropbox_paper_cli.models.cache import SyncResult

cache_app = typer.Typer(name="cache", help="Local metadata cache and search.", no_args_is_help=True)


def _get_cache_service(db: CacheDatabase) -> CacheService:
    """Get a CacheService with an authenticated HTTP client. Patched in tests."""
    svc = _get_auth_service()
    client = svc.get_http_client()
    return CacheService(conn=db.conn, client=client)


_PHASE_LABELS = {
    "metadata": "Syncing metadata",
    "preview_urls": "Fetching Paper preview URLs",
    "shared_links": "Fetching sharing links",
    "done": "Done",
}


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
        fmt.verbose(f"Sync path={path!r} full={full} concurrency={concurrency}")
        svc = _get_cache_service(db)
        is_tty = sys.stderr.isatty() and not fmt.json_mode

        if is_tty:
            result = _sync_with_rich_progress(svc, full=full, path=path, concurrency=concurrency)
        else:
            result = _sync_plain(svc, full=full, path=path, concurrency=concurrency)

        fmt.verbose(
            f"Sync done: type={result.sync_type} added={result.added} "
            f"updated={result.updated} removed={result.removed} ({result.duration_seconds}s)"
        )

        if fmt.json_mode:
            fmt.success(
                {
                    "status": "synced",
                    "added": result.added,
                    "updated": result.updated,
                    "removed": result.removed,
                    "total": result.total,
                    "links_cached": result.links_cached,
                    "duration_seconds": result.duration_seconds,
                    "sync_type": result.sync_type,
                }
            )
        else:
            typer.echo(f"  Added:   {result.added} items")
            typer.echo(f"  Updated: {result.updated} items")
            typer.echo(f"  Removed: {result.removed} items")
            typer.echo(f"  Total:   {result.total:,} items in cache")
            if result.links_cached > 0:
                typer.echo(f"  Links:   {result.links_cached} sharing URLs cached")
            typer.echo("")
            typer.echo(f"✓ Sync complete ({result.duration_seconds}s)")


def _sync_with_rich_progress(
    svc: CacheService, *, full: bool, path: str, concurrency: int
) -> SyncResult:
    """Run sync with a rich spinner + progress counters on stderr."""
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        TextColumn("{task.fields[detail]}", style="dim"),
        TimeElapsedColumn(),
        transient=True,
        console=_stderr_console(),
    )

    task_id = progress.add_task("Syncing metadata...", detail="", total=None)

    def on_progress(r: SyncResult) -> None:
        label = _PHASE_LABELS.get(r.phase, r.phase)
        if r.phase == "metadata":
            total = r.added + r.updated
            detail = f"{total:,} items" if total else ""
            progress.update(task_id, description=f"{label}...", detail=detail)
        elif r.phase in ("preview_urls", "shared_links"):
            progress.update(task_id, description=f"{label}...", detail="")
        else:
            progress.update(task_id, description=label, detail="")

    async def _run() -> SyncResult:
        async with svc.client:
            return await svc.sync(
                force_full=full,
                path=path,
                concurrency=concurrency,
                on_progress=on_progress,
            )

    with progress:
        return asyncio.run(_run())


def _sync_plain(svc: CacheService, *, full: bool, path: str, concurrency: int) -> SyncResult:
    """Run sync with no interactive progress (non-TTY / JSON mode)."""

    async def _run() -> SyncResult:
        async with svc.client:
            return await svc.sync(force_full=full, path=path, concurrency=concurrency)

    return asyncio.run(_run())


def _stderr_console():
    """Create a rich Console that writes to stderr."""
    from rich.console import Console  # noqa: PLC0415

    return Console(stderr=True)


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
        fmt.verbose(f"Searching query={query!r} type={item_type} limit={limit}")
        from dropbox_paper_cli.services.cache_service import search_cache

        results = search_cache(db.conn, query, item_type=item_type, limit=limit)
        fmt.verbose(f"Found {len(results)} results")

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
