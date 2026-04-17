"""Tests for sharing_service: get_folder_metadata, list_folder_members, pagination."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from dropbox_paper_cli.lib.errors import NotFoundError
from dropbox_paper_cli.services.sharing_service import SharingService


@pytest.fixture
def mock_client():
    """Provide an AsyncMock standing in for DropboxHttpClient."""
    return AsyncMock()


@pytest.fixture
def service(mock_client):
    return SharingService(client=mock_client)


def _member_dict(
    account_id="dbid:1",
    display_name="Jane Doe",
    email="jane@ex.com",
    access_tag="owner",
) -> dict:
    return {
        "user": {
            "account_id": account_id,
            "display_name": display_name,
            "email": email,
        },
        "access_type": {".tag": access_tag},
    }


def _members_response(members: list[dict], *, cursor: str | None = None) -> dict:
    resp: dict = {"users": members}
    if cursor is not None:
        resp["cursor"] = cursor
    return resp


class TestGetSharingInfo:
    """get_sharing_info retrieves folder metadata and members."""

    async def test_get_sharing_info_success(self, service, mock_client):
        folder_meta = {
            "shared_folder_id": "sf:123",
            "name": "Project Notes",
            "path_display": "/Project Notes",
        }
        members_resp = _members_response(
            [
                _member_dict("dbid:1", "Jane Doe", "jane@ex.com", "owner"),
                _member_dict("dbid:2", "Bob Smith", "bob@ex.com", "editor"),
            ]
        )

        mock_client.rpc.side_effect = [folder_meta, members_resp]

        info = await service.get_sharing_info("sf:123")

        assert info.shared_folder_id == "sf:123"
        assert info.name == "Project Notes"
        assert len(info.members) == 2
        assert info.members[0].display_name == "Jane Doe"
        assert info.members[1].access_type == "editor"

    async def test_get_sharing_info_with_pagination(self, service, mock_client):
        folder_meta = {
            "shared_folder_id": "sf:123",
            "name": "Project",
            "path_display": "/Project",
        }
        first_page = _members_response(
            [_member_dict("dbid:1", "Jane", "j@ex.com", "owner")],
            cursor="cursor_page2",
        )
        second_page = _members_response(
            [_member_dict("dbid:2", "Bob", "b@ex.com", "editor")],
        )

        mock_client.rpc.side_effect = [folder_meta, first_page, second_page]

        info = await service.get_sharing_info("sf:123")

        assert len(info.members) == 2
        # Verify the continue call used the cursor
        mock_client.rpc.assert_any_call(
            "sharing/list_folder_members/continue",
            {"cursor": "cursor_page2"},
        )

    async def test_get_sharing_info_not_found(self, service, mock_client):
        mock_client.rpc.side_effect = NotFoundError("Shared folder not found")

        with pytest.raises(NotFoundError):
            await service.get_sharing_info("sf:nonexistent")

    async def test_get_sharing_info_empty_members(self, service, mock_client):
        folder_meta = {
            "shared_folder_id": "sf:123",
            "name": "Empty Folder",
            "path_display": "/Empty Folder",
        }
        members_resp = _members_response([])

        mock_client.rpc.side_effect = [folder_meta, members_resp]

        info = await service.get_sharing_info("sf:123")

        assert len(info.members) == 0
