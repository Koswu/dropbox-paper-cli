"""Interactive search TUI powered by Textual."""

from __future__ import annotations

import sqlite3
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


class SearchApp(App):
    """Interactive search over the local Dropbox metadata cache."""

    TITLE = "Dropbox Paper Search"

    CSS = """
    #search-input {
        dock: top;
        margin: 0 1;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #results-table {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "Quit", priority=True),
        Binding("f2", "get_link", "Get Link", priority=True),
        Binding("f3", "open_link", "Open in Browser", priority=True),
        Binding("f4", "read_doc", "Read Doc", priority=True),
        Binding("down", "focus_table", "Focus Table", show=False),
    ]

    status_text: reactive[str] = reactive("")

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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(
            placeholder="Type to search...",
            value=self._initial_query,
            id="search-input",
        )
        with Vertical():
            yield DataTable(id="results-table")
        yield Static(self.status_text, id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("", "Type", "Name", "Path")
        if self._initial_query:
            self._run_search(self._initial_query)

    async def action_quit(self) -> None:
        """Cancel all running workers before quitting."""
        self.workers.cancel_all()
        self.exit()

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

    def _run_search(self, query: str) -> None:
        query = query.strip()
        if not query:
            self._results = []
            self._update_table([])
            self.status_text = ""
            return
        self._do_search(query)

    @work(thread=True, exclusive=True, group="search")
    def _do_search(self, query: str) -> None:
        """Run search in a background thread with its own DB connection."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            from dropbox_paper_cli.services.cache_service import CacheService

            svc = CacheService(conn=conn, client=None)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            results = svc.search(query, limit=100)
            conn.close()
            self._results = results
            self.call_from_thread(self._update_table, results)
            self.call_from_thread(setattr, self, "status_text", f"{len(results)} result(s)")
        except Exception as e:
            self.call_from_thread(setattr, self, "status_text", f"Search error: {e}")

    def _update_table(self, results: list[CachedMetadata]) -> None:
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for r in results:
            icon = {"paper": "📝", "folder": "📁", "file": "📄"}.get(r.item_type, "📄")
            name = f"{r.name}/" if r.is_dir else r.name
            table.add_row(icon, r.item_type, name, r.path_display, key=r.id)

    def _get_selected(self) -> CachedMetadata | None:
        table = self.query_one("#results-table", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self._results):
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        for r in self._results:
            if r.id == row_key.value:
                return r
        return None

    def _get_dropbox_service(self):
        """Create an authenticated DropboxService with a short timeout for TUI use."""
        from dropbox_paper_cli.services.auth_service import AuthService
        from dropbox_paper_cli.services.dropbox_service import DropboxService

        svc = AuthService()
        client = svc.get_client(timeout=15)
        return DropboxService(client=client)

    def action_get_link(self) -> None:
        item = self._get_selected()
        if item is None:
            self.status_text = "No item selected"
            return
        if item.is_dir:
            self.status_text = "Sharing links not supported for folders"
            return
        self.status_text = f"Getting link for {item.name}..."
        self._fetch_link(item)

    @work(thread=True, exclusive=True, group="network")
    def _fetch_link(self, item: CachedMetadata) -> None:
        try:
            dbx = self._get_dropbox_service()
            result = dbx.get_or_create_sharing_link(item.id)
            url = result["url"]
            self.call_from_thread(setattr, self, "status_text", f"🔗 {url}")
        except Exception as e:
            self.call_from_thread(setattr, self, "status_text", f"Error: {e}")

    def action_open_link(self) -> None:
        item = self._get_selected()
        if item is None:
            self.status_text = "No item selected"
            return
        if item.is_dir:
            self.status_text = "Cannot open folders in browser"
            return
        self.status_text = f"Opening {item.name} in browser..."
        self._open_in_browser(item)

    @work(thread=True, exclusive=True, group="network")
    def _open_in_browser(self, item: CachedMetadata) -> None:
        try:
            dbx = self._get_dropbox_service()
            result = dbx.get_or_create_sharing_link(item.id)
            url = result["url"]
            webbrowser.open(url)
            self.call_from_thread(setattr, self, "status_text", f"Opened {url}")
        except Exception as e:
            self.call_from_thread(setattr, self, "status_text", f"Error: {e}")

    def action_read_doc(self) -> None:
        item = self._get_selected()
        if item is None:
            self.status_text = "No item selected"
            return
        if item.item_type != "paper":
            self.status_text = "Preview only supported for Paper documents"
            return
        self.status_text = f"Reading {item.name}..."
        self._read_document(item)

    @work(thread=True, exclusive=True, group="network")
    def _read_document(self, item: CachedMetadata) -> None:
        try:
            dbx = self._get_dropbox_service()
            content = dbx.export_paper_content(item.id)
            preview = content[:500].replace("\n", " ↵ ")
            if len(content) > 500:
                preview += "…"
            self.call_from_thread(setattr, self, "status_text", f"📄 {preview}")
        except Exception as e:
            self.call_from_thread(setattr, self, "status_text", f"Error: {e}")


def run_search_tui(initial_query: str = "", db_path: Path | None = None) -> None:
    """Launch the interactive search TUI."""
    app = SearchApp(db_path=db_path, initial_query=initial_query)
    app.run()
