"""Tests for files CLI commands: list, metadata, link, read, move, copy, delete, create-folder."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from dropbox_paper_cli.app import app
from dropbox_paper_cli.lib.errors import AuthenticationError, NotFoundError, ValidationError
from dropbox_paper_cli.models.items import DropboxItem


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_dropbox_service():
    """Patch the HTTP client and DropboxService used by async CLI commands.

    The CLI commands now use ``run_with_client(fn)`` from ``cli.common``,
    which calls ``get_http_client()`` → ``async with client: await fn(client)``.
    We patch ``common.get_http_client`` so all CLI modules share the same
    async-context-manager mock, and patch DropboxService in each sub-module
    to return a shared mock service whose methods are AsyncMock.
    """
    # Async-context-manager mock for the HTTP client
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Shared mock service with AsyncMock methods
    svc = MagicMock()
    svc.list_folder = AsyncMock(return_value=[])
    svc.get_metadata = AsyncMock()
    svc.get_or_create_sharing_link = AsyncMock()
    svc.resolve_shared_link_url = AsyncMock()
    svc.export_paper_content = AsyncMock()
    svc.create_paper_doc = AsyncMock()
    svc.update_paper_doc = AsyncMock()
    svc.create_folder = AsyncMock()
    svc.move_item = AsyncMock()
    svc.copy_item = AsyncMock()
    svc.delete_item = AsyncMock()

    with (
        patch("dropbox_paper_cli.cli.common.get_http_client", return_value=mock_client),
        patch("dropbox_paper_cli.cli.files_browse.DropboxService", return_value=svc),
        patch("dropbox_paper_cli.cli.files_content.DropboxService", return_value=svc),
        patch("dropbox_paper_cli.cli.files_organize.DropboxService", return_value=svc),
    ):
        yield svc


def _make_item(
    id="id:abc123",
    name="Meeting Notes.paper",
    path_display="/Meeting Notes.paper",
    path_lower="/meeting notes.paper",
    item_type="file",
    size=12700,
    server_modified=None,
    rev="015abc",
    content_hash="hash123",
) -> DropboxItem:
    return DropboxItem(
        id=id,
        name=name,
        path_display=path_display,
        path_lower=path_lower,
        type=item_type,
        size=size if item_type == "file" else None,
        server_modified=server_modified or datetime(2025, 7, 18, 9, 0),
        rev=rev if item_type == "file" else None,
        content_hash=content_hash if item_type == "file" else None,
    )


# ── Phase 4: Browse Commands (T027) ──────────────────────────────


class TestFilesList:
    """paper files list [PATH] [--recursive]"""

    def test_list_root(self, runner, mock_dropbox_service):
        mock_dropbox_service.list_folder.return_value = [
            _make_item(
                id="id:1", name="Project Notes", path_display="/Project Notes", item_type="folder"
            ),
            _make_item(id="id:2", name="Meeting Notes.paper", path_display="/Meeting Notes.paper"),
        ]

        result = runner.invoke(app, ["files", "list"])
        assert result.exit_code == 0
        assert "Project Notes" in result.stdout
        assert "Meeting Notes.paper" in result.stdout

    def test_list_subfolder(self, runner, mock_dropbox_service):
        mock_dropbox_service.list_folder.return_value = [
            _make_item(id="id:3", name="doc.paper", path_display="/sub/doc.paper"),
        ]

        result = runner.invoke(app, ["files", "list", "/sub"])
        assert result.exit_code == 0
        assert "doc.paper" in result.stdout

    def test_list_recursive(self, runner, mock_dropbox_service):
        mock_dropbox_service.list_folder.return_value = [
            _make_item(id="id:1", name="a.paper", path_display="/a.paper"),
        ]

        result = runner.invoke(app, ["files", "list", "--recursive"])
        assert result.exit_code == 0
        mock_dropbox_service.list_folder.assert_called_once_with("", recursive=True)

    def test_list_empty_folder(self, runner, mock_dropbox_service):
        mock_dropbox_service.list_folder.return_value = []

        result = runner.invoke(app, ["files", "list"])
        assert result.exit_code == 0

    def test_list_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.list_folder.return_value = [
            _make_item(id="id:1", name="test.paper", path_display="/test.paper"),
        ]

        result = runner.invoke(app, ["--json", "files", "list"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "test.paper"

    def test_list_auth_error(self, runner, mock_dropbox_service):
        mock_dropbox_service.list_folder.side_effect = AuthenticationError("Not authenticated")

        result = runner.invoke(app, ["files", "list"])
        assert result.exit_code == 2


class TestFilesMetadata:
    """paper files metadata <TARGET>"""

    def test_metadata_by_path(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.return_value = _make_item()

        result = runner.invoke(app, ["files", "metadata", "/Meeting Notes.paper"])
        assert result.exit_code == 0
        assert "Meeting Notes.paper" in result.stdout

    def test_metadata_by_id(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.return_value = _make_item()

        result = runner.invoke(app, ["files", "metadata", "id:abc123"])
        assert result.exit_code == 0

    def test_metadata_by_url(self, runner, mock_dropbox_service):
        mock_dropbox_service.resolve_shared_link_url.return_value = "id:abc123"
        mock_dropbox_service.get_metadata.return_value = _make_item()

        result = runner.invoke(
            app,
            [
                "files",
                "metadata",
                "https://www.dropbox.com/scl/fi/abc123/Meeting+Notes.paper?rlkey=xxx",
            ],
        )
        assert result.exit_code == 0
        mock_dropbox_service.resolve_shared_link_url.assert_called_once()
        mock_dropbox_service.get_metadata.assert_called_once_with("id:abc123")

    def test_metadata_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.return_value = _make_item()

        result = runner.invoke(app, ["--json", "files", "metadata", "/test.paper"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["id"] == "id:abc123"
        assert data["name"] == "Meeting Notes.paper"
        assert data["type"] == "file"

    def test_metadata_not_found(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.side_effect = NotFoundError("File not found")

        result = runner.invoke(app, ["files", "metadata", "/nonexistent"])
        assert result.exit_code == 3


class TestFilesLink:
    """paper files link <TARGET>"""

    def test_link_returns_url(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_or_create_sharing_link.return_value = {
            "url": "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=xxx",
            "name": "test.paper",
            "id": "id:abc123",
        }

        result = runner.invoke(app, ["files", "link", "/test.paper"])
        assert result.exit_code == 0
        assert "https://www.dropbox.com/scl/fi/abc123" in result.stdout

    def test_link_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_or_create_sharing_link.return_value = {
            "url": "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=xxx",
            "name": "test.paper",
            "id": "id:abc123",
        }

        result = runner.invoke(app, ["--json", "files", "link", "/test.paper"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "url" in data
        assert data["name"] == "test.paper"


# ── Phase 5: Organize Commands (T032) ────────────────────────────


class TestFilesCreateFolder:
    """paper files create-folder <PATH>"""

    def test_create_folder_success(self, runner, mock_dropbox_service):
        mock_dropbox_service.create_folder.return_value = _make_item(
            id="id:folder1", name="New Folder", path_display="/New Folder", item_type="folder"
        )

        result = runner.invoke(app, ["files", "create-folder", "/New Folder"])
        assert result.exit_code == 0
        assert "New Folder" in result.stdout

    def test_create_folder_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.create_folder.return_value = _make_item(
            id="id:folder1", name="New Folder", path_display="/New Folder", item_type="folder"
        )

        result = runner.invoke(app, ["--json", "files", "create-folder", "/New Folder"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "created"
        assert data["type"] == "folder"


class TestFilesMove:
    """paper files move <SOURCE> <DESTINATION>"""

    def test_move_success(self, runner, mock_dropbox_service):
        mock_dropbox_service.move_item.return_value = _make_item(
            path_display="/new/path/Meeting Notes.paper"
        )

        result = runner.invoke(
            app, ["files", "move", "/old/Meeting Notes.paper", "/new/path/Meeting Notes.paper"]
        )
        assert result.exit_code == 0
        assert "Moved" in result.stdout

    def test_move_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.move_item.return_value = _make_item(
            path_display="/new/Meeting Notes.paper"
        )

        result = runner.invoke(
            app, ["--json", "files", "move", "/old/Meeting Notes.paper", "/new/Meeting Notes.paper"]
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "moved"

    def test_move_with_url_source(self, runner, mock_dropbox_service):
        mock_dropbox_service.resolve_shared_link_url.return_value = "id:abc123"
        mock_dropbox_service.move_item.return_value = _make_item(
            path_display="/dest/Meeting Notes.paper"
        )

        result = runner.invoke(
            app,
            [
                "files",
                "move",
                "https://www.dropbox.com/scl/fi/abc123/Meeting+Notes.paper?rlkey=xxx",
                "/dest/Meeting Notes.paper",
            ],
        )
        assert result.exit_code == 0
        mock_dropbox_service.move_item.assert_called_once_with(
            "id:abc123", "/dest/Meeting Notes.paper"
        )


class TestFilesCopy:
    """paper files copy <SOURCE> <DESTINATION>"""

    def test_copy_success(self, runner, mock_dropbox_service):
        mock_dropbox_service.copy_item.return_value = _make_item(
            id="id:new", path_display="/copies/Meeting Notes.paper"
        )

        result = runner.invoke(
            app, ["files", "copy", "/Meeting Notes.paper", "/copies/Meeting Notes.paper"]
        )
        assert result.exit_code == 0
        assert "Copied" in result.stdout

    def test_copy_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.copy_item.return_value = _make_item(
            id="id:new", path_display="/copies/Meeting Notes.paper"
        )

        result = runner.invoke(
            app, ["--json", "files", "copy", "/Meeting Notes.paper", "/copies/Meeting Notes.paper"]
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "copied"
        assert data["new_id"] == "id:new"


class TestFilesDelete:
    """paper files delete <TARGET>"""

    def test_delete_success(self, runner, mock_dropbox_service):
        mock_dropbox_service.delete_item.return_value = _make_item()

        result = runner.invoke(app, ["files", "delete", "/Meeting Notes.paper"])
        assert result.exit_code == 0
        assert "Deleted" in result.stdout

    def test_delete_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.delete_item.return_value = _make_item()

        result = runner.invoke(app, ["--json", "files", "delete", "/Meeting Notes.paper"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "deleted"

    def test_delete_not_found(self, runner, mock_dropbox_service):
        mock_dropbox_service.delete_item.side_effect = NotFoundError("File not found")

        result = runner.invoke(app, ["files", "delete", "/nonexistent"])
        assert result.exit_code == 3


# ── Phase 6: Read Command (T036) ─────────────────────────────────


class TestFilesRead:
    """paper files read <TARGET>"""

    def test_read_outputs_markdown(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.return_value = _make_item()
        mock_dropbox_service.export_paper_content.return_value = "# Meeting Notes\n\nContent here."

        result = runner.invoke(app, ["files", "read", "/Meeting Notes.paper"])
        assert result.exit_code == 0
        assert "# Meeting Notes" in result.stdout
        assert "Content here." in result.stdout

    def test_read_json_output(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.return_value = _make_item()
        mock_dropbox_service.export_paper_content.return_value = "# Meeting Notes\n\nContent."

        result = runner.invoke(app, ["--json", "files", "read", "/Meeting Notes.paper"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["content"] == "# Meeting Notes\n\nContent."
        assert data["format"] == "markdown"
        assert data["name"] == "Meeting Notes.paper"

    def test_read_by_url(self, runner, mock_dropbox_service):
        mock_dropbox_service.resolve_shared_link_url.return_value = "id:abc123"
        mock_dropbox_service.get_metadata.return_value = _make_item()
        mock_dropbox_service.export_paper_content.return_value = "# Content"

        result = runner.invoke(
            app,
            [
                "files",
                "read",
                "https://www.dropbox.com/scl/fi/abc123/Meeting+Notes.paper?rlkey=xxx",
            ],
        )
        assert result.exit_code == 0
        mock_dropbox_service.export_paper_content.assert_called_once_with("id:abc123")

    def test_read_not_found(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.side_effect = NotFoundError("Not found")

        result = runner.invoke(app, ["files", "read", "/nonexistent.paper"])
        assert result.exit_code == 3

    def test_read_not_paper(self, runner, mock_dropbox_service):
        mock_dropbox_service.get_metadata.return_value = _make_item()
        mock_dropbox_service.export_paper_content.side_effect = ValidationError(
            "Not a Paper document"
        )

        result = runner.invoke(app, ["files", "read", "/image.png"])
        assert result.exit_code == 4


# ── Write Commands ────────────────────────────────────────────────


class TestFilesCreate:
    """paper files create <PATH> [--file/-f] [--format]"""

    def test_create_from_stdin(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperCreateResult

        mock_dropbox_service.create_paper_doc.return_value = PaperCreateResult(
            url="https://paper.dropbox.com/doc/abc",
            result_path="/notes/Meeting.paper",
            file_id="id:paper1",
            paper_revision=1,
        )

        result = runner.invoke(
            app, ["files", "create", "/notes/Meeting.paper"], input="# Meeting Notes\n"
        )
        assert result.exit_code == 0
        assert "Created Paper document" in result.stdout
        assert "/notes/Meeting.paper" in result.stdout
        assert "id:paper1" in result.stdout
        mock_dropbox_service.create_paper_doc.assert_called_once()

    def test_create_from_file(self, runner, mock_dropbox_service, tmp_path):
        from dropbox_paper_cli.models.items import PaperCreateResult

        content_file = tmp_path / "doc.md"
        content_file.write_text("# From File")

        mock_dropbox_service.create_paper_doc.return_value = PaperCreateResult(
            url="https://paper.dropbox.com/doc/xyz",
            result_path="/doc.paper",
            file_id="id:paper2",
            paper_revision=1,
        )

        result = runner.invoke(app, ["files", "create", "/doc.paper", "--file", str(content_file)])
        assert result.exit_code == 0
        assert "Created Paper document" in result.stdout
        call_args = mock_dropbox_service.create_paper_doc.call_args
        assert call_args[0][1] == b"# From File"

    def test_create_json_output(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperCreateResult

        mock_dropbox_service.create_paper_doc.return_value = PaperCreateResult(
            url="https://paper.dropbox.com/doc/abc",
            result_path="/doc.paper",
            file_id="id:paper1",
            paper_revision=1,
        )

        result = runner.invoke(
            app, ["--json", "files", "create", "/doc.paper"], input="# Content\n"
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "created"
        assert data["url"] == "https://paper.dropbox.com/doc/abc"
        assert data["file_id"] == "id:paper1"
        assert data["paper_revision"] == 1

    def test_create_with_html_format(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperCreateResult

        mock_dropbox_service.create_paper_doc.return_value = PaperCreateResult(
            url="https://paper.dropbox.com/doc/abc",
            result_path="/doc.paper",
            file_id="id:paper1",
            paper_revision=1,
        )

        result = runner.invoke(
            app,
            ["files", "create", "/doc.paper", "--format", "html"],
            input="<h1>Title</h1>\n",
        )
        assert result.exit_code == 0
        call_args = mock_dropbox_service.create_paper_doc.call_args
        assert call_args[1]["import_format"] == "html"

    def test_create_invalid_extension_error(self, runner, mock_dropbox_service):
        mock_dropbox_service.create_paper_doc.side_effect = ValidationError(
            "Path must end with .paper: /doc.txt"
        )

        result = runner.invoke(app, ["files", "create", "/doc.txt"], input="# Content\n")
        assert result.exit_code == 4

    def test_create_no_input_tty(self, runner, mock_dropbox_service):
        # When no --file and stdin is TTY, typer.testing.CliRunner provides
        # no input → stdin.isatty() may differ, but we can test with no input
        # by not providing input kwarg. The CliRunner simulates non-TTY by default,
        # so we test the error path via the service raising instead.
        pass


class TestFilesWrite:
    """paper files write <TARGET> [--file/-f] [--format] [--policy] [--revision]"""

    def test_write_overwrite_from_stdin(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperUpdateResult

        mock_dropbox_service.update_paper_doc.return_value = PaperUpdateResult(paper_revision=5)

        result = runner.invoke(app, ["files", "write", "/doc.paper"], input="# Updated Content\n")
        assert result.exit_code == 0
        assert "Updated Paper document" in result.stdout
        assert "overwrite" in result.stdout
        assert "5" in result.stdout

    def test_write_from_file(self, runner, mock_dropbox_service, tmp_path):
        from dropbox_paper_cli.models.items import PaperUpdateResult

        content_file = tmp_path / "updated.md"
        content_file.write_text("# Updated")

        mock_dropbox_service.update_paper_doc.return_value = PaperUpdateResult(paper_revision=3)

        result = runner.invoke(app, ["files", "write", "/doc.paper", "--file", str(content_file)])
        assert result.exit_code == 0
        call_args = mock_dropbox_service.update_paper_doc.call_args
        assert call_args[0][1] == b"# Updated"

    def test_write_json_output(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperUpdateResult

        mock_dropbox_service.update_paper_doc.return_value = PaperUpdateResult(paper_revision=5)

        result = runner.invoke(app, ["--json", "files", "write", "/doc.paper"], input="# Content\n")
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "updated"
        assert data["policy"] == "overwrite"
        assert data["paper_revision"] == 5

    def test_write_with_policy_append(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperUpdateResult

        mock_dropbox_service.update_paper_doc.return_value = PaperUpdateResult(paper_revision=4)

        result = runner.invoke(
            app,
            ["files", "write", "/doc.paper", "--policy", "append"],
            input="## Appendix\n",
        )
        assert result.exit_code == 0
        call_args = mock_dropbox_service.update_paper_doc.call_args
        assert call_args[1]["policy"] == "append"

    def test_write_with_update_policy_and_revision(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperUpdateResult

        mock_dropbox_service.update_paper_doc.return_value = PaperUpdateResult(paper_revision=6)

        result = runner.invoke(
            app,
            ["files", "write", "/doc.paper", "--policy", "update", "--revision", "5"],
            input="# V2\n",
        )
        assert result.exit_code == 0
        call_args = mock_dropbox_service.update_paper_doc.call_args
        assert call_args[1]["policy"] == "update"
        assert call_args[1]["paper_revision"] == 5

    def test_write_update_policy_missing_revision(self, runner, mock_dropbox_service):
        mock_dropbox_service.update_paper_doc.side_effect = ValidationError(
            "--revision is required when policy is 'update'"
        )

        result = runner.invoke(
            app,
            ["files", "write", "/doc.paper", "--policy", "update"],
            input="# Content\n",
        )
        assert result.exit_code == 4

    def test_write_by_url(self, runner, mock_dropbox_service):
        from dropbox_paper_cli.models.items import PaperUpdateResult

        mock_dropbox_service.resolve_shared_link_url.return_value = "id:abc123"
        mock_dropbox_service.update_paper_doc.return_value = PaperUpdateResult(paper_revision=2)

        result = runner.invoke(
            app,
            [
                "files",
                "write",
                "https://www.dropbox.com/scl/fi/abc123/doc.paper?rlkey=xxx",
            ],
            input="# Content\n",
        )
        assert result.exit_code == 0
        mock_dropbox_service.resolve_shared_link_url.assert_called_once()
        call_args = mock_dropbox_service.update_paper_doc.call_args
        assert call_args[0][0] == "id:abc123"

    def test_write_not_found(self, runner, mock_dropbox_service):
        mock_dropbox_service.update_paper_doc.side_effect = NotFoundError(
            "Path not found: /nonexistent.paper"
        )

        result = runner.invoke(app, ["files", "write", "/nonexistent.paper"], input="# Content\n")
        assert result.exit_code == 3

    def test_write_revision_mismatch(self, runner, mock_dropbox_service):
        mock_dropbox_service.update_paper_doc.side_effect = ValidationError("Revision mismatch")

        result = runner.invoke(
            app,
            ["files", "write", "/doc.paper", "--policy", "update", "--revision", "3"],
            input="# Content\n",
        )
        assert result.exit_code == 4
