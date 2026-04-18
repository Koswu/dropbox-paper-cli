"""CachedMetadata dataclass for local metadata cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# Re-export for backward compatibility — importers can still do:
#   from dropbox_paper_cli.models.cache import SyncResult, SyncState
from dropbox_paper_cli.models.sync import SyncResult as SyncResult
from dropbox_paper_cli.models.sync import SyncState as SyncState


@dataclass
class CachedMetadata:
    """A locally-stored metadata entry in the SQLite cache."""

    id: str
    name: str
    path_display: str
    path_lower: str
    is_dir: bool
    item_type: str = "file"  # 'paper', 'file', or 'folder'
    parent_path: str | None = None
    size_bytes: int | None = None
    server_modified: str | None = None
    rev: str | None = None
    content_hash: str | None = None
    url: str | None = None
    synced_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )

    def to_row(self) -> tuple:
        """Convert to a tuple for SQLite INSERT/REPLACE."""
        return (
            self.id,
            self.name,
            self.path_display,
            self.path_lower,
            1 if self.is_dir else 0,
            self.item_type,
            self.parent_path,
            self.size_bytes,
            self.server_modified,
            self.rev,
            self.content_hash,
            self.url,
            self.synced_at,
        )

    @classmethod
    def from_row(cls, row: tuple) -> CachedMetadata:
        """Create from a SQLite row tuple."""
        return cls(
            id=row[0],
            name=row[1],
            path_display=row[2],
            path_lower=row[3],
            is_dir=bool(row[4]),
            item_type=row[5] if len(row) > 5 else "file",
            parent_path=row[6] if len(row) > 6 else None,
            size_bytes=row[7] if len(row) > 7 else None,
            server_modified=row[8] if len(row) > 8 else None,
            rev=row[9] if len(row) > 9 else None,
            content_hash=row[10] if len(row) > 10 else None,
            url=row[11] if len(row) > 11 else None,
            synced_at=row[12] if len(row) > 12 else "",
        )
