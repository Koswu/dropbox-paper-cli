"""Sharing service: async shared folder info and member lists via DropboxHttpClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dropbox_paper_cli.models.sharing import MemberInfo, SharingInfo

if TYPE_CHECKING:
    from dropbox_paper_cli.lib.http_client import DropboxHttpClient


class SharingService:
    """Wraps Dropbox API v2 sharing operations."""

    def __init__(self, client: DropboxHttpClient) -> None:
        self._client = client

    async def get_sharing_info(self, shared_folder_id: str) -> SharingInfo:
        """Get sharing info for a shared folder including all members.

        Args:
            shared_folder_id: The shared folder ID (e.g., from folder metadata).

        Returns:
            SharingInfo with folder details and member list.

        Raises:
            NotFoundError: If the folder is not found.
        """
        folder_data = await self._client.rpc(
            "sharing/get_folder_metadata",
            {"shared_folder_id": shared_folder_id},
        )

        members = await self._list_all_members(shared_folder_id)

        return SharingInfo.from_api(folder_data, members)

    async def _list_all_members(self, shared_folder_id: str) -> list[MemberInfo]:
        """List all members of a shared folder with pagination."""
        members: list[MemberInfo] = []

        result = await self._client.rpc(
            "sharing/list_folder_members",
            {"shared_folder_id": shared_folder_id},
        )
        members.extend(MemberInfo.from_api(m) for m in result.get("users", []))

        cursor = result.get("cursor")
        while cursor:
            result = await self._client.rpc(
                "sharing/list_folder_members/continue",
                {"cursor": cursor},
            )
            members.extend(MemberInfo.from_api(m) for m in result.get("users", []))
            cursor = result.get("cursor")

        return members
