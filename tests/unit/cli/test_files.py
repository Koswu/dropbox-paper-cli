"""Tests for files CLI commands: list, metadata, link, read, move, copy, delete, create-folder."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

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
    """Patch the dropbox service factory used by CLI commands."""
    with patch("dropbox_paper_cli.cli.files._get_dropbox_service") as mock_get:
        svc = MagicMock()
        mock_get.return_value = svc
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
