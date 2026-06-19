"""DropboxItem and PaperDocument dataclasses with API response mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    modified_by: str | None = None  # account id of the last user to modify the file

    @property
    def is_paper(self) -> bool:
        """True if this is a Dropbox Paper document (.paper extension)."""
        return self.name.endswith(".paper")

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DropboxItem:
        """Create a DropboxItem from a Dropbox API JSON response dict.

        Handles both file and folder entries by inspecting the ``.tag`` field.
        """
        tag = data.get(".tag", "file")
        if tag == "folder":
            return cls(
                id=data["id"],
                name=data["name"],
                path_display=data.get("path_display", ""),
                path_lower=data.get("path_lower", ""),
                type="folder",
            )
        else:
            server_modified = None
            if "server_modified" in data:
                # Dropbox returns ISO 8601: "2025-07-18T12:00:00Z"
                raw = data["server_modified"]
                if isinstance(raw, str):
                    server_modified = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                else:
                    server_modified = raw
            return cls(
                id=data["id"],
                name=data["name"],
                path_display=data.get("path_display", ""),
                path_lower=data.get("path_lower", ""),
                type="file",
                size=data.get("size"),
                server_modified=server_modified,
                rev=data.get("rev"),
                content_hash=data.get("content_hash"),
                modified_by=data.get("sharing_info", {}).get("modified_by"),
            )


@dataclass
class DocumentOwnership:
    """Author/owner information for a file, assembled from sharing metadata.

    Dropbox's public API does not expose a Paper document's original creator,
    so this captures the closest reliable signals: the file's owner(s) and the
    display name of the last user to modify it.
    """

    owner_names: list[str] = field(default_factory=list)  # explicit owner display name(s)
    owner_team: str | None = None  # owning team name, when the file is team-owned
    is_self_owned: bool = False  # the authenticated account owns this file
    last_edited_by: str | None = None  # display name of the last modifier

    def owner_label(self) -> str | None:
        """Best human-readable owner string, or None if nothing is known."""
        if self.owner_names:
            return ", ".join(self.owner_names)
        if self.is_self_owned:
            return "you"
        if self.owner_team:
            return f"{self.owner_team} (team)"
        return None


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

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PaperCreateResult:
        """Create from API JSON response."""
        return cls(
            url=data["url"],
            result_path=data["result_path"],
            file_id=data["file_id"],
            paper_revision=data["paper_revision"],
        )


@dataclass
class PaperUpdateResult:
    """Result of updating an existing Paper document via the v2 API."""

    paper_revision: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PaperUpdateResult:
        """Create from API JSON response."""
        return cls(paper_revision=data["paper_revision"])
