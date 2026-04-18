"""Tests for dropbox_service: browse, organize, and read operations via AsyncMock DropboxHttpClient."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from dropbox_paper_cli.lib.errors import NotFoundError, ValidationError
from dropbox_paper_cli.services.dropbox_service import DropboxService


@pytest.fixture
def mock_client():
    """Provide an AsyncMock standing in for DropboxHttpClient."""
    return AsyncMock()


@pytest.fixture
def service(mock_client):
    """DropboxService wrapping a mock client."""
    return DropboxService(client=mock_client)


def _file_entry(
    *,
    id="id:file1",
    name="test.paper",
    path_display="/test.paper",
    path_lower="/test.paper",
    size=1024,
    server_modified="2025-07-18T09:00:00Z",
    rev="015abc",
    content_hash="hash123",
) -> dict:
    return {
        ".tag": "file",
        "id": id,
        "name": name,
        "path_display": path_display,
        "path_lower": path_lower,
        "size": size,
        "server_modified": server_modified,
        "rev": rev,
        "content_hash": content_hash,
    }


def _folder_entry(
    *,
    id="id:folder1",
    name="Project Notes",
    path_display="/Project Notes",
    path_lower="/project notes",
) -> dict:
    return {
        ".tag": "folder",
        "id": id,
        "name": name,
        "path_display": path_display,
        "path_lower": path_lower,
    }


# ── Phase 4: Browse Operations (T026) ────────────────────────────


class TestListFolder:
    """list_folder returns items from files/list_folder with pagination."""

    async def test_list_folder_returns_items(self, service, mock_client):
        mock_client.rpc.return_value = {
            "entries": [_folder_entry(), _file_entry()],
            "has_more": False,
            "cursor": "cursor1",
        }

        items = await service.list_folder("")
        assert len(items) == 2
        mock_client.rpc.assert_called_once()

    async def test_list_folder_paginates(self, service, mock_client):
        mock_client.rpc.side_effect = [
            {
                "entries": [_file_entry(id="id:1", name="a.paper")],
                "has_more": True,
                "cursor": "cursor_page2",
            },
            {
                "entries": [_file_entry(id="id:2", name="b.paper")],
                "has_more": False,
                "cursor": "cursor_end",
            },
        ]

        items = await service.list_folder("")
        assert len(items) == 2
        mock_client.rpc.assert_any_call("files/list_folder/continue", {"cursor": "cursor_page2"})

    async def test_list_folder_recursive(self, service, mock_client):
        mock_client.rpc.return_value = {
            "entries": [_file_entry()],
            "has_more": False,
            "cursor": "c",
        }

        await service.list_folder("", recursive=True)
        mock_client.rpc.assert_called_once_with(
            "files/list_folder", {"path": "", "recursive": True}
        )

    async def test_list_folder_empty(self, service, mock_client):
        mock_client.rpc.return_value = {"entries": [], "has_more": False, "cursor": "c"}

        items = await service.list_folder("/empty")
        assert items == []

    async def test_list_folder_subfolder(self, service, mock_client):
        mock_client.rpc.return_value = {
            "entries": [_file_entry()],
            "has_more": False,
            "cursor": "c",
        }

        await service.list_folder("/subfolder")
        mock_client.rpc.assert_called_once_with(
            "files/list_folder", {"path": "/subfolder", "recursive": False}
        )


class TestGetMetadata:
    """get_metadata returns a DropboxItem for a file or folder."""

    async def test_get_metadata_file(self, service, mock_client):
        mock_client.rpc.return_value = _file_entry()

        item = await service.get_metadata("/test.paper")
        assert item.name == "test.paper"
        assert item.type == "file"

    async def test_get_metadata_folder(self, service, mock_client):
        mock_client.rpc.return_value = _folder_entry()

        item = await service.get_metadata("/Project Notes")
        assert item.name == "Project Notes"
        assert item.type == "folder"

    async def test_get_metadata_not_found(self, service, mock_client):
        mock_client.rpc.side_effect = NotFoundError("Not found: path/not_found/...")

        with pytest.raises(NotFoundError):
            await service.get_metadata("/nonexistent")


class TestGetOrCreateSharingLink:
    """get_or_create_sharing_link returns a sharing URL."""

    async def test_creates_sharing_link(self, service, mock_client):
        mock_client.rpc.return_value = {
            "url": "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=xxx",
            "name": "test.paper",
            "id": "id:abc123",
        }

        result = await service.get_or_create_sharing_link("/test.paper")
        assert result["url"] == "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=xxx"

    async def test_returns_existing_link_on_conflict(self, service, mock_client):
        # The http_client raises ValidationError with the JSON body for 409 shared_link_already_exists
        body = {
            "error_summary": "shared_link_already_exists/...",
            "error": {
                "shared_link_already_exists": {
                    "metadata": {
                        "url": "https://www.dropbox.com/scl/fi/abc123/test.paper?rlkey=existing",
                        "name": "test.paper",
                        "id": "id:abc123",
                    }
                }
            },
        }
        mock_client.rpc.side_effect = ValidationError(
            f"shared_link_already_exists:{json.dumps(body)}"
        )

        result = await service.get_or_create_sharing_link("/test.paper")
        assert "existing" in result["url"]


# ── Phase 5: Organize Operations (T031) ──────────────────────────


class TestMoveItem:
    """move_item calls files/move_v2 and returns the moved item."""

    async def test_move_item_success(self, service, mock_client):
        mock_client.rpc.return_value = {
            "metadata": _file_entry(path_display="/new/test.paper"),
        }

        item = await service.move_item("/old/test.paper", "/new/test.paper")
        assert item.path_display == "/new/test.paper"
        mock_client.rpc.assert_called_once_with(
            "files/move_v2", {"from_path": "/old/test.paper", "to_path": "/new/test.paper"}
        )

    async def test_move_item_not_found(self, service, mock_client):
        mock_client.rpc.side_effect = NotFoundError("Not found: from_lookup/not_found/...")

        with pytest.raises(NotFoundError):
            await service.move_item("/nonexistent", "/dest")


class TestCopyItem:
    """copy_item calls files/copy_v2 and returns the new copy."""

    async def test_copy_item_success(self, service, mock_client):
        mock_client.rpc.return_value = {
            "metadata": _file_entry(id="id:new", path_display="/copies/test.paper"),
        }

        item = await service.copy_item("/test.paper", "/copies/test.paper")
        assert item.id == "id:new"
        mock_client.rpc.assert_called_once_with(
            "files/copy_v2", {"from_path": "/test.paper", "to_path": "/copies/test.paper"}
        )

    async def test_copy_item_not_found(self, service, mock_client):
        mock_client.rpc.side_effect = NotFoundError("Not found: from_lookup/not_found/...")

        with pytest.raises(NotFoundError):
            await service.copy_item("/nonexistent", "/dest")


class TestDeleteItem:
    """delete_item calls files/delete_v2 and returns the deleted item."""

    async def test_delete_item_success(self, service, mock_client):
        mock_client.rpc.return_value = {
            "metadata": _file_entry(path_display="/test.paper"),
        }

        item = await service.delete_item("/test.paper")
        assert item.name == "test.paper"
        mock_client.rpc.assert_called_once_with("files/delete_v2", {"path": "/test.paper"})

    async def test_delete_item_not_found(self, service, mock_client):
        mock_client.rpc.side_effect = NotFoundError("Not found: path_lookup/not_found/...")

        with pytest.raises(NotFoundError):
            await service.delete_item("/nonexistent")


class TestCreateFolder:
    """create_folder calls files/create_folder_v2 and returns the new folder."""

    async def test_create_folder_success(self, service, mock_client):
        mock_client.rpc.return_value = {
            "metadata": _folder_entry(
                id="id:newfolder", name="New Folder", path_display="/New Folder"
            ),
        }

        item = await service.create_folder("/New Folder")
        assert item.name == "New Folder"
        assert item.type == "folder"
        mock_client.rpc.assert_called_once_with("files/create_folder_v2", {"path": "/New Folder"})


# ── Phase 6: Read Content (T035) ─────────────────────────────────


class TestExportPaperContent:
    """export_paper_content calls content_download and returns markdown."""

    async def test_export_paper_content_success(self, service, mock_client):
        mock_client.content_download.return_value = (
            b"# Meeting Notes\n\nContent here.",
            {"name": "Meeting Notes.paper", "export_hash": "exporthash"},
        )

        content = await service.export_paper_content("/Meeting Notes.paper")
        assert content == "# Meeting Notes\n\nContent here."
        mock_client.content_download.assert_called_once_with(
            "files/export",
            {"path": "/Meeting Notes.paper", "export_format": "markdown"},
        )

    async def test_export_paper_content_not_found(self, service, mock_client):
        mock_client.content_download.side_effect = NotFoundError("Not found: path/not_found/...")

        with pytest.raises(NotFoundError):
            await service.export_paper_content("/nonexistent.paper")

    async def test_export_non_paper_file(self, service, mock_client):
        mock_client.content_download.side_effect = ValidationError("Not a Paper document")

        with pytest.raises(ValidationError):
            await service.export_paper_content("/image.png")


# ── Write Content ────────────────────────────────────────────────


class TestCreatePaperDoc:
    """create_paper_doc calls content_upload and returns PaperCreateResult."""

    async def test_create_success(self, service, mock_client):
        from dropbox_paper_cli.models.items import PaperCreateResult

        mock_client.content_upload.return_value = {
            "url": "https://paper.dropbox.com/doc/abc",
            "result_path": "/notes/Meeting.paper",
            "file_id": "id:paper1",
            "paper_revision": 1,
        }

        result = await service.create_paper_doc(
            "/notes/Meeting.paper", b"# Meeting Notes", import_format="markdown"
        )
        assert isinstance(result, PaperCreateResult)
        assert result.url == "https://paper.dropbox.com/doc/abc"
        assert result.result_path == "/notes/Meeting.paper"
        assert result.file_id == "id:paper1"
        assert result.paper_revision == 1
        mock_client.content_upload.assert_called_once()

    async def test_create_html_format(self, service, mock_client):
        mock_client.content_upload.return_value = {
            "url": "https://paper.dropbox.com/doc/abc",
            "result_path": "/doc.paper",
            "file_id": "id:paper2",
            "paper_revision": 1,
        }

        await service.create_paper_doc("/doc.paper", b"<h1>Title</h1>", import_format="html")

        call_args = mock_client.content_upload.call_args
        params = call_args[0][1]
        assert params["import_format"] == {".tag": "html"}

    async def test_create_invalid_extension(self, service, mock_client):
        mock_client.content_upload.side_effect = ValidationError("Path must end with .paper")

        with pytest.raises(ValidationError, match="must end with .paper"):
            await service.create_paper_doc("/doc.txt", b"content")

    async def test_create_invalid_path(self, service, mock_client):
        mock_client.content_upload.side_effect = ValidationError("Invalid path")

        with pytest.raises(ValidationError, match="Invalid path"):
            await service.create_paper_doc("/\x00bad.paper", b"content")

    async def test_create_email_unverified(self, service, mock_client):
        mock_client.content_upload.side_effect = ValidationError("Email must be verified")

        with pytest.raises(ValidationError, match="Email must be verified"):
            await service.create_paper_doc("/doc.paper", b"content")

    async def test_create_paper_disabled(self, service, mock_client):
        mock_client.content_upload.side_effect = ValidationError("Paper is disabled for this team")

        with pytest.raises(ValidationError, match="Paper is disabled"):
            await service.create_paper_doc("/doc.paper", b"content")

    async def test_create_invalid_format(self, service):
        with pytest.raises(ValidationError, match="Invalid import format"):
            await service.create_paper_doc("/doc.paper", b"content", import_format="docx")


class TestUpdatePaperDoc:
    """update_paper_doc calls content_upload and returns PaperUpdateResult."""

    async def test_update_overwrite_success(self, service, mock_client):
        from dropbox_paper_cli.models.items import PaperUpdateResult

        mock_client.content_upload.return_value = {"paper_revision": 5}

        result = await service.update_paper_doc(
            "/doc.paper", b"# Updated", import_format="markdown", policy="overwrite"
        )
        assert isinstance(result, PaperUpdateResult)
        assert result.paper_revision == 5
        mock_client.content_upload.assert_called_once()

    async def test_update_with_revision(self, service, mock_client):
        mock_client.content_upload.return_value = {"paper_revision": 6}

        result = await service.update_paper_doc(
            "/doc.paper", b"# V2", policy="update", paper_revision=5
        )
        assert result.paper_revision == 6

        call_args = mock_client.content_upload.call_args
        params = call_args[0][1]
        assert params["paper_revision"] == 5
        assert params["doc_update_policy"] == {".tag": "update"}

    async def test_update_append(self, service, mock_client):
        mock_client.content_upload.return_value = {"paper_revision": 3}

        await service.update_paper_doc("/doc.paper", b"## Appendix", policy="append")

        call_args = mock_client.content_upload.call_args
        params = call_args[0][1]
        assert params["doc_update_policy"] == {".tag": "append"}

    async def test_update_requires_revision_for_update_policy(self, service):
        with pytest.raises(ValidationError, match="--revision is required"):
            await service.update_paper_doc("/doc.paper", b"content", policy="update")

    async def test_update_not_found(self, service, mock_client):
        mock_client.content_upload.side_effect = NotFoundError("Not found: path/not_found/...")

        with pytest.raises(NotFoundError):
            await service.update_paper_doc("/nonexistent.paper", b"content")

    async def test_update_doc_archived(self, service, mock_client):
        mock_client.content_upload.side_effect = ValidationError("Document is archived")

        with pytest.raises(ValidationError, match="archived"):
            await service.update_paper_doc("/doc.paper", b"content")

    async def test_update_doc_deleted(self, service, mock_client):
        mock_client.content_upload.side_effect = NotFoundError("Document is deleted")

        with pytest.raises(NotFoundError, match="deleted"):
            await service.update_paper_doc("/doc.paper", b"content")

    async def test_update_revision_mismatch(self, service, mock_client):
        mock_client.content_upload.side_effect = ValidationError("Revision mismatch")

        with pytest.raises(ValidationError, match="Revision mismatch"):
            await service.update_paper_doc(
                "/doc.paper", b"content", policy="update", paper_revision=3
            )

    async def test_update_invalid_format(self, service):
        with pytest.raises(ValidationError, match="Invalid import format"):
            await service.update_paper_doc("/doc.paper", b"content", import_format="rtf")

    async def test_update_invalid_policy(self, service):
        with pytest.raises(ValidationError, match="Invalid update policy"):
            await service.update_paper_doc("/doc.paper", b"content", policy="replace")
