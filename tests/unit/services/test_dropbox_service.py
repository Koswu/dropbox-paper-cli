"""Tests for dropbox_service: browse, organize, and read operations with mock SDK responses."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import dropbox.exceptions
import dropbox.files
import dropbox.sharing
import pytest

from dropbox_paper_cli.services.dropbox_service import DropboxService


@pytest.fixture
def mock_dbx():
    """Provide a mock Dropbox SDK client."""
    return MagicMock(spec=dropbox.Dropbox)


@pytest.fixture
def service(mock_dbx):
    """DropboxService wrapping a mock client."""
    return DropboxService(client=mock_dbx)


def _make_file_metadata(
    id="id:file1",
    name="test.paper",
    path_display="/test.paper",
    path_lower="/test.paper",
    size=1024,
    server_modified=None,
    rev="015abc",
    content_hash="hash123",
):
    m = MagicMock(spec=dropbox.files.FileMetadata)
    m.id = id
    m.name = name
    m.path_display = path_display
    m.path_lower = path_lower
    m.size = size
    m.server_modified = server_modified or datetime(2025, 7, 18, 9, 0)
    m.rev = rev
    m.content_hash = content_hash
    return m


def _make_folder_metadata(
    id="id:folder1",
    name="Project Notes",
    path_display="/Project Notes",
    path_lower="/project notes",
):
    m = MagicMock(spec=dropbox.files.FolderMetadata)
    m.id = id
    m.name = name
    m.path_display = path_display
    m.path_lower = path_lower
    return m


# ── Phase 4: Browse Operations (T026) ────────────────────────────


class TestListFolder:
    """list_folder returns items from files_list_folder with pagination."""

    def test_list_folder_returns_items(self, service, mock_dbx):
        file_entry = _make_file_metadata()
        folder_entry = _make_folder_metadata()

        result = MagicMock()
        result.entries = [folder_entry, file_entry]
        result.has_more = False
        mock_dbx.files_list_folder.return_value = result

        items = service.list_folder("")
        assert len(items) == 2
        mock_dbx.files_list_folder.assert_called_once()

    def test_list_folder_paginates(self, service, mock_dbx):
        file1 = _make_file_metadata(id="id:1", name="a.paper")
        file2 = _make_file_metadata(id="id:2", name="b.paper")

        result1 = MagicMock()
        result1.entries = [file1]
        result1.has_more = True
        result1.cursor = "cursor_page2"

        result2 = MagicMock()
        result2.entries = [file2]
        result2.has_more = False

        mock_dbx.files_list_folder.return_value = result1
        mock_dbx.files_list_folder_continue.return_value = result2

        items = service.list_folder("")
        assert len(items) == 2
        mock_dbx.files_list_folder_continue.assert_called_once_with("cursor_page2")

    def test_list_folder_recursive(self, service, mock_dbx):
        result = MagicMock()
        result.entries = [_make_file_metadata()]
        result.has_more = False
        mock_dbx.files_list_folder.return_value = result

        service.list_folder("", recursive=True)
        call_kwargs = mock_dbx.files_list_folder.call_args
        assert (
            call_kwargs[1].get("recursive") is True or call_kwargs.kwargs.get("recursive") is True
        )

    def test_list_folder_empty(self, service, mock_dbx):
        result = MagicMock()
        result.entries = []
        result.has_more = False
        mock_dbx.files_list_folder.return_value = result

        items = service.list_folder("/empty")
        assert items == []

    def test_list_folder_subfolder(self, service, mock_dbx):
        result = MagicMock()
        result.entries = [_make_file_metadata()]
        result.has_more = False
        mock_dbx.files_list_folder.return_value = result

        service.list_folder("/subfolder")
        mock_dbx.files_list_folder.assert_called_once_with("/subfolder", recursive=False)


class TestGetMetadata:
    """get_metadata returns a DropboxItem for a file or folder."""

    def test_get_metadata_file(self, service, mock_dbx):
        file_meta = _make_file_metadata()
        mock_dbx.files_get_metadata.return_value = file_meta

        item = service.get_metadata("/test.paper")
        assert item.name == "test.paper"
        assert item.type == "file"

    def test_get_metadata_folder(self, service, mock_dbx):
        folder_meta = _make_folder_metadata()
        mock_dbx.files_get_metadata.return_value = folder_meta

        item = service.get_metadata("/Project Notes")
        assert item.name == "Project Notes"
        assert item.type == "folder"

    def test_get_metadata_not_found(self, service, mock_dbx):
        from dropbox_paper_cli.lib.errors import NotFoundError

        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="not found",
            user_message_locale="en",
        )
        error.error.is_path.return_value = True
        mock_dbx.files_get_metadata.side_effect = error

        with pytest.raises(NotFoundError):
            service.get_metadata("/nonexistent")


class TestGetOrCreateSharingLink:
    """get_or_create_sharing_link returns a sharing URL."""

    def test_creates_sharing_link(self, service, mock_dbx):
        link_result = MagicMock()
        link_result.url = "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=xxx"
        link_result.name = "test.paper"
        link_result.id = "id:abc123"
        mock_dbx.sharing_create_shared_link_with_settings.return_value = link_result

        result = service.get_or_create_sharing_link("/test.paper")
        assert result["url"] == "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=xxx"

    def test_returns_existing_link_on_conflict(self, service, mock_dbx):
        # When a link already exists, SDK raises ApiError with shared_link_already_exists
        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="shared link already exists",
            user_message_locale="en",
        )
        error.error.is_shared_link_already_exists.return_value = True
        shared_link_meta = MagicMock()
        shared_link_meta.url = "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=existing"
        shared_link_meta.name = "test.paper"
        shared_link_meta.id = "id:abc123"
        error.error.get_shared_link_already_exists.return_value.get_metadata.return_value = (
            shared_link_meta
        )
        mock_dbx.sharing_create_shared_link_with_settings.side_effect = error

        result = service.get_or_create_sharing_link("/test.paper")
        assert "existing" in result["url"]


# ── Phase 5: Organize Operations (T031) ──────────────────────────


class TestMoveItem:
    """move_item calls files_move_v2 and returns the moved item."""

    def test_move_item_success(self, service, mock_dbx):
        moved = _make_file_metadata(path_display="/new/test.paper")
        result = MagicMock()
        result.metadata = moved
        mock_dbx.files_move_v2.return_value = result

        item = service.move_item("/old/test.paper", "/new/test.paper")
        assert item.path_display == "/new/test.paper"
        mock_dbx.files_move_v2.assert_called_once_with("/old/test.paper", "/new/test.paper")

    def test_move_item_not_found(self, service, mock_dbx):
        from dropbox_paper_cli.lib.errors import NotFoundError

        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="not found",
            user_message_locale="en",
        )
        error.error.is_from_lookup.return_value = True
        mock_dbx.files_move_v2.side_effect = error

        with pytest.raises(NotFoundError):
            service.move_item("/nonexistent", "/dest")


class TestCopyItem:
    """copy_item calls files_copy_v2 and returns the new copy."""

    def test_copy_item_success(self, service, mock_dbx):
        copied = _make_file_metadata(id="id:new", path_display="/copies/test.paper")
        result = MagicMock()
        result.metadata = copied
        mock_dbx.files_copy_v2.return_value = result

        item = service.copy_item("/test.paper", "/copies/test.paper")
        assert item.id == "id:new"
        mock_dbx.files_copy_v2.assert_called_once_with("/test.paper", "/copies/test.paper")

    def test_copy_item_not_found(self, service, mock_dbx):
        from dropbox_paper_cli.lib.errors import NotFoundError

        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="not found",
            user_message_locale="en",
        )
        error.error.is_from_lookup.return_value = True
        mock_dbx.files_copy_v2.side_effect = error

        with pytest.raises(NotFoundError):
            service.copy_item("/nonexistent", "/dest")


class TestDeleteItem:
    """delete_item calls files_delete_v2 and returns the deleted item."""

    def test_delete_item_success(self, service, mock_dbx):
        deleted = _make_file_metadata(path_display="/test.paper")
        result = MagicMock()
        result.metadata = deleted
        mock_dbx.files_delete_v2.return_value = result

        item = service.delete_item("/test.paper")
        assert item.name == "test.paper"
        mock_dbx.files_delete_v2.assert_called_once_with("/test.paper")

    def test_delete_item_not_found(self, service, mock_dbx):
        from dropbox_paper_cli.lib.errors import NotFoundError

        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="not found",
            user_message_locale="en",
        )
        error.error.is_path_lookup.return_value = True
        mock_dbx.files_delete_v2.side_effect = error

        with pytest.raises(NotFoundError):
            service.delete_item("/nonexistent")


class TestCreateFolder:
    """create_folder calls files_create_folder_v2 and returns the new folder."""

    def test_create_folder_success(self, service, mock_dbx):
        folder = _make_folder_metadata(
            id="id:newfolder", name="New Folder", path_display="/New Folder"
        )
        result = MagicMock()
        result.metadata = folder
        mock_dbx.files_create_folder_v2.return_value = result

        item = service.create_folder("/New Folder")
        assert item.name == "New Folder"
        assert item.type == "folder"
        mock_dbx.files_create_folder_v2.assert_called_once_with("/New Folder")


# ── Phase 6: Read Content (T035) ─────────────────────────────────


class TestExportPaperContent:
    """export_paper_content calls files_export and returns markdown."""

    def test_export_paper_content_success(self, service, mock_dbx):
        export_meta = MagicMock()
        export_meta.name = "Meeting Notes.paper"
        export_meta.export_hash = "exporthash"

        response = MagicMock()
        response.content = b"# Meeting Notes\n\nContent here."

        mock_dbx.files_export.return_value = (export_meta, response)

        content = service.export_paper_content("/Meeting Notes.paper")
        assert content == "# Meeting Notes\n\nContent here."
        mock_dbx.files_export.assert_called_once_with(
            "/Meeting Notes.paper", export_format="markdown"
        )

    def test_export_paper_content_not_found(self, service, mock_dbx):
        from dropbox_paper_cli.lib.errors import NotFoundError

        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="not found",
            user_message_locale="en",
        )
        error.error.is_path.return_value = True
        mock_dbx.files_export.side_effect = error

        with pytest.raises(NotFoundError):
            service.export_paper_content("/nonexistent.paper")

    def test_export_non_paper_file(self, service, mock_dbx):
        from dropbox_paper_cli.lib.errors import ValidationError

        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="not exportable",
            user_message_locale="en",
        )
        error.error.is_path.return_value = False
        error.error.is_non_exportable.return_value = True
        mock_dbx.files_export.side_effect = error

        with pytest.raises(ValidationError):
            service.export_paper_content("/image.png")
