"""CachedMetadata, SyncState, and SyncResult dataclasses for local metadata cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class CachedMetadata:
    """A locally-stored metadata entry in the SQLite cache."""

    id: str
    name: str
    path_display: str
    path_lower: str
    is_dir: bool
    parent_path: str | None = None
    size_bytes: int | None = None
    server_modified: str | None = None
    rev: str | None = None
    content_hash: str | None = None
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
            self.parent_path,
            self.size_bytes,
            self.server_modified,
            self.rev,
            self.content_hash,
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
            parent_path=row[5],
            size_bytes=row[6],
            server_modified=row[7],
            rev=row[8],
            content_hash=row[9],
            synced_at=row[10] if len(row) > 10 else "",
        )


@dataclass
class SyncState:
    """Tracks the cursor position for incremental sync."""

    key: str = "default"
    cursor: str | None = None
    last_sync_at: str | None = None
    total_items: int = 0


@dataclass
class SyncResult:
    """Summary of a sync operation."""

    added: int = 0
    updated: int = 0
    removed: int = 0
    total: int = 0
    duration_seconds: float = 0.0
    sync_type: str = "full"
