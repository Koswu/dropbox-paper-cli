"""Tests for SharingInfo and MemberInfo dataclasses and API response mapping."""

from __future__ import annotations

from dropbox_paper_cli.models.sharing import MemberInfo, SharingInfo


class TestMemberInfo:
    """MemberInfo creation and API mapping."""

    def test_create_member(self):
        member = MemberInfo(
            account_id="dbid:AAD123",
            display_name="Jane Doe",
            email="jane@example.com",
            access_type="owner",
        )
        assert member.display_name == "Jane Doe"
        assert member.access_type == "owner"

    def test_from_api(self):
        api_dict = {
            "user": {
                "account_id": "dbid:AAD123",
                "display_name": "Jane Doe",
                "email": "jane@example.com",
            },
            "access_type": {".tag": "owner"},
        }

        member = MemberInfo.from_api(api_dict)
        assert member.account_id == "dbid:AAD123"
        assert member.display_name == "Jane Doe"
        assert member.email == "jane@example.com"
        assert member.access_type == "owner"


class TestSharingInfo:
    """SharingInfo creation and API mapping."""

    def test_create_sharing_info(self):
        info = SharingInfo(
            shared_folder_id="sf:123",
            name="Project Notes",
            path_display="/Project Notes",
            members=[
                MemberInfo("dbid:1", "Jane", "jane@ex.com", "owner"),
                MemberInfo("dbid:2", "Bob", "bob@ex.com", "editor"),
            ],
        )
        assert info.shared_folder_id == "sf:123"
        assert len(info.members) == 2

    def test_from_api(self):
        folder_data = {
            "shared_folder_id": "sf:123",
            "name": "Project Notes",
            "path_display": "/Project Notes",
        }

        members = [
            MemberInfo("dbid:1", "Jane", "jane@ex.com", "owner"),
        ]

        info = SharingInfo.from_api(folder_data, members)
        assert info.shared_folder_id == "sf:123"
        assert info.name == "Project Notes"
        assert len(info.members) == 1

    def test_from_api_no_path(self):
        folder_data = {
            "shared_folder_id": "sf:456",
            "name": "Shared",
            "path_lower": "/shared",
        }

        info = SharingInfo.from_api(folder_data, [])
        assert info.path_display == "/shared"

    def test_default_empty_members(self):
        info = SharingInfo(shared_folder_id="sf:1", name="Test")
        assert info.members == []
