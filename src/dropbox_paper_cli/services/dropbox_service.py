"""Dropbox service: file/folder operations wrapping the Dropbox SDK."""

from __future__ import annotations

import dropbox
import dropbox.exceptions
import dropbox.files
import dropbox.sharing

from dropbox_paper_cli.lib.errors import NotFoundError, ValidationError
from dropbox_paper_cli.lib.retry import with_retry
from dropbox_paper_cli.models.items import DropboxItem


class DropboxService:
    """Wraps Dropbox SDK file and folder operations.

    All SDK calls use @with_retry for transient error handling.
    """

    def __init__(self, client: dropbox.Dropbox) -> None:
        self._dbx = client

    # ── Browse Operations (US2) ───────────────────────────────────

    @with_retry()
    def list_folder(self, path: str, *, recursive: bool = False) -> list[DropboxItem]:
        """List files and folders at a Dropbox path with pagination.

        Args:
            path: Dropbox path (empty string for root).
            recursive: If True, list all items recursively.

        Returns:
            List of DropboxItem objects.
        """
        # Dropbox API requires empty string for root, not "/"
        if path == "/":
            path = ""
        result = self._dbx.files_list_folder(path, recursive=recursive)
        items: list[DropboxItem] = []
        items.extend(DropboxItem.from_sdk(entry) for entry in result.entries)

        while result.has_more:
            result = self._dbx.files_list_folder_continue(result.cursor)
            items.extend(DropboxItem.from_sdk(entry) for entry in result.entries)

        return items

    @with_retry()
    def get_metadata(self, path: str) -> DropboxItem:
        """Get metadata for a specific file or folder.

        Args:
            path: Dropbox path or ID (e.g., 'id:abc123').

        Raises:
            NotFoundError: If the path does not exist.
        """
        try:
            metadata = self._dbx.files_get_metadata(path)
            return DropboxItem.from_sdk(metadata)
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_path") and e.error.is_path():
                raise NotFoundError(f"Path not found: {path}") from e
            raise

    @with_retry()
    def get_shared_folder_id(self, path: str) -> str | None:
        """Get the shared_folder_id for a folder, or None if not shared.

        The Dropbox sharing API requires a numeric shared_folder_id, not the
        regular file/folder ID.
        """
        try:
            metadata = self._dbx.files_get_metadata(path)
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_path") and e.error.is_path():
                raise NotFoundError(f"Path not found: {path}") from e
            raise

        sharing_info = getattr(metadata, "sharing_info", None)
        if sharing_info and hasattr(sharing_info, "shared_folder_id"):
            return sharing_info.shared_folder_id
        return None

    @with_retry()
    def get_or_create_sharing_link(self, path: str) -> dict[str, str]:
        """Get or create a sharing link for a file.

        Returns:
            Dict with url, name, and id keys.
        """
        try:
            settings = dropbox.sharing.SharedLinkSettings()
            link = self._dbx.sharing_create_shared_link_with_settings(path, settings=settings)
            return {"url": link.url, "name": link.name, "id": link.id}
        except dropbox.exceptions.ApiError as e:
            if (
                hasattr(e.error, "is_shared_link_already_exists")
                and e.error.is_shared_link_already_exists()
            ):
                existing = e.error.get_shared_link_already_exists().get_metadata()
                return {"url": existing.url, "name": existing.name, "id": existing.id}
            raise

    # ── Organize Operations (US3) ─────────────────────────────────

    @with_retry()
    def move_item(self, from_path: str, to_path: str) -> DropboxItem:
        """Move a file or folder.

        Raises:
            NotFoundError: If the source path does not exist.
        """
        try:
            result = self._dbx.files_move_v2(from_path, to_path)
            return DropboxItem.from_sdk(result.metadata)
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_from_lookup") and e.error.is_from_lookup():
                raise NotFoundError(f"Source not found: {from_path}") from e
            raise

    @with_retry()
    def copy_item(self, from_path: str, to_path: str) -> DropboxItem:
        """Copy a file or folder.

        Raises:
            NotFoundError: If the source path does not exist.
        """
        try:
            result = self._dbx.files_copy_v2(from_path, to_path)
            return DropboxItem.from_sdk(result.metadata)
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_from_lookup") and e.error.is_from_lookup():
                raise NotFoundError(f"Source not found: {from_path}") from e
            raise

    @with_retry()
    def delete_item(self, path: str) -> DropboxItem:
        """Delete a file or folder.

        Raises:
            NotFoundError: If the path does not exist.
        """
        try:
            result = self._dbx.files_delete_v2(path)
            return DropboxItem.from_sdk(result.metadata)
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_path_lookup") and e.error.is_path_lookup():
                raise NotFoundError(f"Path not found: {path}") from e
            raise

    @with_retry()
    def create_folder(self, path: str) -> DropboxItem:
        """Create a new folder.

        Returns:
            DropboxItem for the created folder.
        """
        result = self._dbx.files_create_folder_v2(path)
        return DropboxItem.from_sdk(result.metadata)

    # ── Read Content (US4) ────────────────────────────────────────

    @with_retry()
    def export_paper_content(self, path: str) -> str:
        """Export a Paper document as Markdown.

        Args:
            path: Dropbox path or ID.

        Returns:
            Markdown string content.

        Raises:
            NotFoundError: If the path does not exist.
            ValidationError: If the file is not a Paper document.
        """
        try:
            _metadata, response = self._dbx.files_export(path, export_format="markdown")
            return response.content.decode()
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_path") and e.error.is_path():
                raise NotFoundError(f"Path not found: {path}") from e
            if hasattr(e.error, "is_non_exportable") and e.error.is_non_exportable():
                raise ValidationError(f"Not a Paper document: {path}") from e
            raise

    # ── URL Resolution ────────────────────────────────────────────

    @with_retry()
    def resolve_shared_link_url(self, url: str) -> str:
        """Resolve a Dropbox shared link URL to a file/folder ID.

        Uses the sharing_get_shared_link_metadata API to extract the real ID.

        Returns:
            File/folder ID string (e.g. 'id:abc123').

        Raises:
            NotFoundError: If the URL does not resolve.
        """
        try:
            meta = self._dbx.sharing_get_shared_link_metadata(url)
            return meta.id
        except dropbox.exceptions.ApiError as e:
            raise NotFoundError(f"Could not resolve URL: {url}") from e
