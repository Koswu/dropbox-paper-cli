"""SyncState and SyncResult dataclasses for sync operations."""

from __future__ import annotations

from dataclasses import dataclass


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
    links_cached: int = 0
