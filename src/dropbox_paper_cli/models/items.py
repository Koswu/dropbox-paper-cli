"""DropboxItem and PaperDocument dataclasses with SDK metadata mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DropboxItem:
    """Represents a file or folder in the remote Dropbox namespace."""

    id: str
    name: str
    path_display: str
    path_lower: str
    type: str  # "file" or "folder"
    size: int | None = None
    server_modified: datetime | None = None
    rev: str | None = None
    content_hash: str | None = None

    @property
    def is_paper(self) -> bool:
        """True if this is a Dropbox Paper document (.paper extension)."""
        return self.name.endswith(".paper")

    @classmethod
    def from_sdk(cls, metadata: Any) -> DropboxItem:
        """Create a DropboxItem from a Dropbox SDK metadata object.

        Handles both FileMetadata and FolderMetadata.
        """
        import dropbox.files

        if isinstance(metadata, dropbox.files.FileMetadata):
            return cls(
                id=metadata.id,
                name=metadata.name,
                path_display=metadata.path_display,
                path_lower=metadata.path_lower,
                type="file",
                size=metadata.size,
                server_modified=metadata.server_modified,
                rev=metadata.rev,
                content_hash=metadata.content_hash,
            )
        elif isinstance(metadata, dropbox.files.FolderMetadata):
            return cls(
                id=metadata.id,
                name=metadata.name,
                path_display=metadata.path_display,
                path_lower=metadata.path_lower,
                type="folder",
            )
        else:
            # Fallback: try to infer from class name (for mocks)
            class_name = metadata.__class__.__name__
            if class_name == "FolderMetadata":
                return cls(
                    id=metadata.id,
                    name=metadata.name,
                    path_display=metadata.path_display,
                    path_lower=metadata.path_lower,
                    type="folder",
                )
            else:
                return cls(
                    id=metadata.id,
                    name=metadata.name,
                    path_display=metadata.path_display,
                    path_lower=metadata.path_lower,
                    type="file",
                    size=getattr(metadata, "size", None),
                    server_modified=getattr(metadata, "server_modified", None),
                    rev=getattr(metadata, "rev", None),
                    content_hash=getattr(metadata, "content_hash", None),
                )


@dataclass
class PaperDocument(DropboxItem):
    """A DropboxItem that is a Paper document, with optional markdown content."""

    content_markdown: str | None = None


@dataclass
class PaperCreateResult:
    """Result of creating a new Paper document via the v2 API."""

    url: str
    result_path: str
    file_id: str
    paper_revision: int


@dataclass
class PaperUpdateResult:
    """Result of updating an existing Paper document via the v2 API."""

    paper_revision: int
