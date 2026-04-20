"""Interactive search TUI powered by Textual."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import webbrowser
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static

from dropbox_paper_cli.lib.config import CACHE_DB_PATH
from dropbox_paper_cli.models.cache import CachedMetadata

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class SearchApp(App):
    """Interactive search over the local Dropbox metadata cache."""

    TITLE = "Dropbox Paper Search"

    CSS = """
    #search-input {
        dock: top;
        margin: 0 1;
    }
    #status-bar {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #results-table {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "Quit", priority=True),
        Binding("f2", "get_link", "Copy Link", priority=True),
        Binding("f3", "open_link", "Open", priority=True),
        Binding("f5", "toggle_regex", "Regex", priority=True),
        Binding("down", "focus_table", "Focus Table", show=False),
    ]

    status_text: reactive[str] = reactive("")
    regex_mode: reactive[bool] = reactive(False)

    def __init__(
        self,
        db_path: Path | None = None,
        initial_query: str = "",
    ) -> None:
        super().__init__()
        self._db_path = db_path or CACHE_DB_PATH
        self._initial_query = initial_query
        self._results: list[CachedMetadata] = []
        self._debounce_timer: Timer | None = None
        self._last_result_text: str = ""
        self._spinner_timer: Timer | None = None
        self._spinner_index = 0
        self._spinner_message = ""

    def _get_db_conn(self) -> sqlite3.Connection:
        """Open a WAL-mode connection for background DB writes."""
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(
            placeholder="Type to search...",
            value=self._initial_query,
            id="search-input",
        )
        yield Static(self.status_text, id="status-bar")
        with Vertical():
            yield DataTable(id="results-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("", "Type", "Name", "Path")
        self._refresh_status()
        if self._initial_query:
            self._run_search(self._initial_query)

    def _mode_label(self) -> str:
        return "🔣 Regex Mode" if self.regex_mode else "🔤 Keyword Mode"

    def _refresh_status(self, result_text: str | None = None) -> None:
        """Update status bar with mode indicator and optional result info."""
        if self._spinner_timer is not None:
            return
        if result_text is not None:
            self._last_result_text = result_text
        parts = [self._mode_label()]
        if self._last_result_text:
            parts.append(self._last_result_text)
        self.status_text = "  ".join(parts)

    async def action_quit(self) -> None:
        """Cancel all running workers before quitting."""
        self._stop_spinner()
        self.workers.cancel_all()
        self.exit()

    def _start_spinner(self, message: str) -> None:
        """Start a spinner animation in the status bar."""
        self._stop_spinner()
        self._spinner_message = message
        self._spinner_index = 0
        self._update_spinner()
        self._spinner_timer = self.set_interval(0.1, self._update_spinner)

    def _update_spinner(self) -> None:
        frame = _SPINNER_FRAMES[self._spinner_index % len(_SPINNER_FRAMES)]
        self.status_text = f"{frame} {self._spinner_message}"
        self._spinner_index += 1

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def watch_regex_mode(self, value: bool) -> None:
        try:
            inp = self.query_one("#search-input", Input)
            inp.placeholder = "Type regex pattern..." if value else "Type to search..."
        except Exception:
            pass

    def watch_status_text(self, value: str) -> None:
        try:
            bar = self.query_one("#status-bar", Static)
            bar.update(value)
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
        self._debounce_timer = self.set_timer(0.3, lambda: self._run_search(event.value))

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """When Enter is pressed in the search input, move focus to results."""
        table = self.query_one("#results-table", DataTable)
        if table.row_count > 0:
            table.focus()

    def action_focus_table(self) -> None:
        table = self.query_one("#results-table", DataTable)
        if table.row_count > 0:
            table.focus()

    def action_toggle_regex(self) -> None:
        """Toggle regex search mode and re-run the current query."""
        self.regex_mode = not self.regex_mode
        desc = "Regex ✓" if self.regex_mode else "Regex"
        self.bind("f5", "toggle_regex", description=desc, show=True)
        self.refresh_bindings()
        self._refresh_status()
        inp = self.query_one("#search-input", Input)
        if inp.value.strip():
            self._run_search(inp.value)

    def _run_search(self, query: str) -> None:
        query = query.strip()
        if not query:
            self._results = []
            self._update_table([])
            self._stop_spinner()
            self._refresh_status("")
            return
        self._do_search(query, self.regex_mode)

    @work(thread=True, exclusive=True, group="search")
    def _do_search(self, query: str, regex: bool = False) -> None:
        """Run search in a background thread with its own DB connection."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            from dropbox_paper_cli.services.cache_service import search_cache

            results = search_cache(conn, query, limit=100, regex=regex)
            conn.close()
            self._results = results
            self.call_from_thread(self._update_table, results)
            self.call_from_thread(self._refresh_status, f"{len(results)} result(s)")
        except Exception as e:
            self.call_from_thread(self._refresh_status, f"⚠ {e}")

    def _update_table(self, results: list[CachedMetadata]) -> None:
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for r in results:
            icon = {"paper": "📝", "folder": "📁", "file": "📄"}.get(r.item_type, "📄")
            name = f"{r.name}/" if r.is_dir else r.name
            table.add_row(icon, r.item_type, name, r.path_display, key=r.id)

    def _get_selected(self) -> CachedMetadata | None:
        table = self.query_one("#results-table", DataTable)
        if table.row_count == 0 or not self._results:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        for r in self._results:
            if r.id == row_key.value:
                return r
        return None

    def _run_async(self, fn):
        """Create an HTTP client, enter its async context, and run *fn(client)*."""
        from dropbox_paper_cli.cli.common import get_http_client

        client = get_http_client()

        async def _wrapper():
            async with client:
                return await fn(client)

        return asyncio.run(_wrapper())

    def _try_copy(self, url: str) -> None:
        """Copy URL to clipboard with fallback notification on failure."""
        try:
            self.copy_to_clipboard(url)
            self.notify(f"✅ Copied: {url}", severity="information")
        except Exception:
            self.notify(f"🔗 {url}", severity="information")

    def action_get_link(self) -> None:
        item = self._get_selected()
        if item is None:
            self.notify("No item selected — select a row first", severity="warning")
            return
        if item.url:
            self.status_text = f"🔗 {item.url}"
            self._try_copy(item.url)
            return
        if item.is_dir:
            self.notify("No URL cached for this folder", severity="warning")
            return
        self._start_spinner(f"Getting link for {item.name}...")
        self._fetch_link(item)

    @work(thread=True, exclusive=True, group="network")
    def _fetch_link(self, item: CachedMetadata) -> None:
        try:

            async def _get_link(client):
                from dropbox_paper_cli.services.dropbox_service import DropboxService

                dbx = DropboxService(client=client)
                return await dbx.get_or_create_sharing_link(item.id)

            result = self._run_async(_get_link)
            url = result["url"]
            # Lazy cache: write URL to DB and update in-memory item
            item.url = url
            conn = self._get_db_conn()
            conn.execute("UPDATE metadata SET url = ? WHERE id = ?", (url, item.id))
            conn.commit()
            conn.close()
            self.call_from_thread(self._stop_spinner)
            self.call_from_thread(setattr, self, "status_text", f"🔗 {url}")
            self.call_from_thread(self._try_copy, url)
        except Exception as e:
            self.call_from_thread(self._stop_spinner)
            self.call_from_thread(setattr, self, "status_text", f"Error: {e}")
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def action_open_link(self) -> None:
        item = self._get_selected()
        if item is None:
            self.notify("No item selected — select a row first", severity="warning")
            return
        if item.url:
            webbrowser.open(item.url)
            self.status_text = f"Opened {item.url}"
            return
        if item.is_dir:
            self.notify("No URL cached for this folder", severity="warning")
            return
        self._start_spinner(f"Opening {item.name} in browser...")
        self._open_in_browser(item)

    @work(thread=True, exclusive=True, group="network")
    def _open_in_browser(self, item: CachedMetadata) -> None:
        try:

            async def _get_link(client):
                from dropbox_paper_cli.services.dropbox_service import DropboxService

                dbx = DropboxService(client=client)
                return await dbx.get_or_create_sharing_link(item.id)

            result = self._run_async(_get_link)
            url = result["url"]
            # Lazy cache
            item.url = url
            conn = self._get_db_conn()
            conn.execute("UPDATE metadata SET url = ? WHERE id = ?", (url, item.id))
            conn.commit()
            conn.close()
            webbrowser.open(url)
            self.call_from_thread(self._stop_spinner)
            self.call_from_thread(setattr, self, "status_text", f"Opened {url}")
        except Exception as e:
            self.call_from_thread(self._stop_spinner)
            self.call_from_thread(setattr, self, "status_text", f"Error: {e}")
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")


def run_search_tui(initial_query: str = "", db_path: Path | None = None) -> None:
    """Launch the interactive search TUI."""
    app = SearchApp(db_path=db_path, initial_query=initial_query)
    app.run()
    # Force exit: worker threads may still be blocking on network I/O
    sys.exit(0)
