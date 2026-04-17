"""Tests for sharing_service: get_folder_metadata, list_folder_members, pagination."""

from __future__ import annotations

from unittest.mock import MagicMock

import dropbox.exceptions
import pytest

from dropbox_paper_cli.lib.errors import NotFoundError
from dropbox_paper_cli.services.sharing_service import SharingService


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def service(mock_client):
    return SharingService(client=mock_client)


def _make_member(
    account_id="dbid:1", display_name="Jane Doe", email="jane@ex.com", access_tag="owner"
):
    member = MagicMock()
    member.user.account_id = account_id
    member.user.display_name = display_name
    member.user.email = email
    member.access_type._tag = access_tag
    return member


class TestGetSharingInfo:
    """get_sharing_info retrieves folder metadata and members."""

    def test_get_sharing_info_success(self, service, mock_client):
        # Mock folder metadata
        folder_meta = MagicMock()
        folder_meta.shared_folder_id = "sf:123"
        folder_meta.name = "Project Notes"
        folder_meta.path_display = "/Project Notes"
        mock_client.sharing_get_folder_metadata.return_value = folder_meta

        # Mock members
        members_result = MagicMock()
        members_result.users = [
            _make_member("dbid:1", "Jane Doe", "jane@ex.com", "owner"),
            _make_member("dbid:2", "Bob Smith", "bob@ex.com", "editor"),
        ]
        members_result.cursor = None
        mock_client.sharing_list_folder_members.return_value = members_result

        info = service.get_sharing_info("sf:123")
        assert info.shared_folder_id == "sf:123"
        assert info.name == "Project Notes"
        assert len(info.members) == 2
        assert info.members[0].display_name == "Jane Doe"

    def test_get_sharing_info_with_pagination(self, service, mock_client):
        folder_meta = MagicMock()
        folder_meta.shared_folder_id = "sf:123"
        folder_meta.name = "Project"
        folder_meta.path_display = "/Project"
        mock_client.sharing_get_folder_metadata.return_value = folder_meta

        # First page of members
        first_page = MagicMock()
        first_page.users = [_make_member("dbid:1", "Jane", "j@ex.com", "owner")]
        first_page.cursor = "cursor_page2"
        mock_client.sharing_list_folder_members.return_value = first_page

        # Second page
        second_page = MagicMock()
        second_page.users = [_make_member("dbid:2", "Bob", "b@ex.com", "editor")]
        second_page.cursor = None
        mock_client.sharing_list_folder_members_continue.return_value = second_page

        info = service.get_sharing_info("sf:123")
        assert len(info.members) == 2
        mock_client.sharing_list_folder_members_continue.assert_called_once_with("cursor_page2")

    def test_get_sharing_info_not_found(self, service, mock_client):
        error = dropbox.exceptions.ApiError(
            request_id="req1",
            error=MagicMock(),
            user_message_text="not found",
            user_message_locale="en",
        )
        error.error.is_access_error.return_value = True
        mock_client.sharing_get_folder_metadata.side_effect = error

        with pytest.raises(NotFoundError):
            service.get_sharing_info("sf:nonexistent")

    def test_get_sharing_info_empty_members(self, service, mock_client):
        folder_meta = MagicMock()
        folder_meta.shared_folder_id = "sf:123"
        folder_meta.name = "Empty Folder"
        folder_meta.path_display = "/Empty Folder"
        mock_client.sharing_get_folder_metadata.return_value = folder_meta

        members_result = MagicMock()
        members_result.users = []
        members_result.cursor = None
        mock_client.sharing_list_folder_members.return_value = members_result

        info = service.get_sharing_info("sf:123")
        assert len(info.members) == 0
