"""Tests for DropboxItem and PaperDocument dataclasses including API response mapping."""

from __future__ import annotations

from datetime import UTC, datetime

from dropbox_paper_cli.models.items import DropboxItem, PaperDocument


class TestDropboxItem:
    """DropboxItem holds file/folder metadata from the Dropbox API."""

    def test_file_item_creation(self):
        item = DropboxItem(
            id="id:abc123",
            name="Notes.paper",
            path_display="/Notes.paper",
            path_lower="/notes.paper",
            type="file",
            size=12700,
            server_modified=datetime(2025, 7, 18, tzinfo=UTC),
            rev="015f2b3c",
            content_hash="a1b2c3",
        )
        assert item.id == "id:abc123"
        assert item.name == "Notes.paper"
        assert item.type == "file"
        assert item.size == 12700
        assert item.is_paper is True

    def test_folder_item_creation(self):
        item = DropboxItem(
            id="id:folder1",
            name="Project Notes",
            path_display="/Project Notes",
            path_lower="/project notes",
            type="folder",
        )
        assert item.type == "folder"
        assert item.size is None
        assert item.server_modified is None
        assert item.is_paper is False

    def test_is_paper_detection(self):
        paper = DropboxItem(
            id="id:1",
            name="doc.paper",
            path_display="/doc.paper",
            path_lower="/doc.paper",
            type="file",
        )
        non_paper = DropboxItem(
            id="id:2",
            name="doc.txt",
            path_display="/doc.txt",
            path_lower="/doc.txt",
            type="file",
        )
        assert paper.is_paper is True
        assert non_paper.is_paper is False

    def test_from_file_metadata(self):
        """from_api creates a DropboxItem from a Dropbox API JSON dict (file)."""
        api_dict = {
            ".tag": "file",
            "id": "id:f1",
            "name": "Report.paper",
            "path_display": "/Report.paper",
            "path_lower": "/report.paper",
            "size": 5000,
            "server_modified": "2025-07-18T00:00:00Z",
            "rev": "abc",
            "content_hash": "hash1",
        }

        item = DropboxItem.from_api(api_dict)
        assert item.id == "id:f1"
        assert item.type == "file"
        assert item.size == 5000

    def test_from_folder_metadata(self):
        """from_api creates a DropboxItem from a Dropbox API JSON dict (folder)."""
        api_dict = {
            ".tag": "folder",
            "id": "id:d1",
            "name": "Docs",
            "path_display": "/Docs",
            "path_lower": "/docs",
        }

        item = DropboxItem.from_api(api_dict)
        assert item.id == "id:d1"
        assert item.type == "folder"
        assert item.size is None


class TestPaperDocument:
    """PaperDocument extends DropboxItem with markdown content."""

    def test_creation_with_content(self):
        doc = PaperDocument(
            id="id:p1",
            name="Notes.paper",
            path_display="/Notes.paper",
            path_lower="/notes.paper",
            type="file",
            content_markdown="# Meeting Notes\n\nDiscussion points...",
        )
        assert doc.content_markdown == "# Meeting Notes\n\nDiscussion points..."
        assert doc.is_paper is True
