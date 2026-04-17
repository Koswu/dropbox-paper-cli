"""Sharing service: get shared folder info and member lists."""

from __future__ import annotations

import dropbox
import dropbox.exceptions
import dropbox.sharing

from dropbox_paper_cli.lib.errors import NotFoundError
from dropbox_paper_cli.lib.retry import with_retry
from dropbox_paper_cli.models.sharing import MemberInfo, SharingInfo


class SharingService:
    """Wraps Dropbox SDK sharing operations."""

    def __init__(self, client: dropbox.Dropbox) -> None:
        self._dbx = client

    @with_retry()
    def get_sharing_info(self, shared_folder_id: str) -> SharingInfo:
        """Get sharing info for a shared folder including all members.

        Args:
            shared_folder_id: The shared folder ID (e.g., from folder metadata).

        Returns:
            SharingInfo with folder details and member list.

        Raises:
            NotFoundError: If the folder is not found.
            ValidationError: If the target is not a shared folder.
        """
        try:
            folder_meta = self._dbx.sharing_get_folder_metadata(shared_folder_id)
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_access_error") and e.error.is_access_error():
                raise NotFoundError(
                    f"Shared folder not found or access denied: {shared_folder_id}"
                ) from e
            raise

        # Get members with pagination
        members = self._list_all_members(shared_folder_id)

        return SharingInfo.from_sdk(folder_meta, members)

    def _list_all_members(self, shared_folder_id: str) -> list[MemberInfo]:
        """List all members of a shared folder with pagination."""
        members: list[MemberInfo] = []

        try:
            result = self._dbx.sharing_list_folder_members(shared_folder_id)
            members.extend(MemberInfo.from_sdk(m) for m in result.users)

            while result.cursor:
                result = self._dbx.sharing_list_folder_members_continue(result.cursor)
                members.extend(MemberInfo.from_sdk(m) for m in result.users)
                if not result.cursor:
                    break

        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, "is_access_error") and e.error.is_access_error():
                raise NotFoundError(f"Cannot list members for folder: {shared_folder_id}") from e
            raise

        return members
