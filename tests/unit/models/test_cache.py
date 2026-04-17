"""Tests for CachedMetadata, SyncState, and SyncResult dataclasses."""

from __future__ import annotations

from dropbox_paper_cli.models.cache import CachedMetadata, SyncResult, SyncState


class TestCachedMetadata:
    """CachedMetadata creation, serialization, and row conversion."""

    def test_create_file_entry(self):
        entry = CachedMetadata(
            id="id:file1",
            name="Meeting Notes.paper",
            path_display="/Meeting Notes.paper",
            path_lower="/meeting notes.paper",
            is_dir=False,
            parent_path="/",
            size_bytes=12700,
            server_modified="2025-07-18T09:00:00Z",
            rev="015abc",
            content_hash="hash123",
        )
        assert entry.id == "id:file1"
        assert entry.name == "Meeting Notes.paper"
        assert entry.is_dir is False
        assert entry.size_bytes == 12700

    def test_create_folder_entry(self):
        entry = CachedMetadata(
            id="id:folder1",
            name="Project Notes",
            path_display="/Project Notes",
            path_lower="/project notes",
            is_dir=True,
        )
        assert entry.is_dir is True
        assert entry.size_bytes is None
        assert entry.rev is None

    def test_to_row(self):
        entry = CachedMetadata(
            id="id:1",
            name="test.paper",
            path_display="/test.paper",
            path_lower="/test.paper",
            is_dir=False,
            parent_path="/",
            size_bytes=100,
            server_modified="2025-01-01T00:00:00Z",
            rev="abc",
            content_hash="xyz",
            synced_at="2025-01-01T00:00:00Z",
        )
        row = entry.to_row()
        assert len(row) == 11
        assert row[0] == "id:1"
        assert row[4] == 0  # is_dir as integer

    def test_from_row(self):
        row = (
            "id:1",
            "test.paper",
            "/test.paper",
            "/test.paper",
            1,
            "/",
            None,
            None,
            None,
            None,
            "2025-01-01T00:00:00Z",
        )
        entry = CachedMetadata.from_row(row)
        assert entry.id == "id:1"
        assert entry.is_dir is True

    def test_synced_at_default(self):
        entry = CachedMetadata(
            id="id:1",
            name="test",
            path_display="/test",
            path_lower="/test",
            is_dir=False,
        )
        assert entry.synced_at is not None
        assert len(entry.synced_at) > 0


class TestSyncState:
    """SyncState default values and field access."""

    def test_defaults(self):
        state = SyncState()
        assert state.key == "default"
        assert state.cursor is None
        assert state.last_sync_at is None
        assert state.total_items == 0

    def test_custom_values(self):
        state = SyncState(
            key="default",
            cursor="cursor123",
            last_sync_at="2025-07-18T00:00:00Z",
            total_items=42,
        )
        assert state.cursor == "cursor123"
        assert state.total_items == 42


class TestSyncResult:
    """SyncResult default values and field access."""

    def test_defaults(self):
        result = SyncResult()
        assert result.added == 0
        assert result.updated == 0
        assert result.removed == 0
        assert result.total == 0
        assert result.duration_seconds == 0.0
        assert result.sync_type == "full"

    def test_custom_values(self):
        result = SyncResult(added=10, updated=5, removed=2, total=100, sync_type="incremental")
        assert result.added == 10
        assert result.sync_type == "incremental"
