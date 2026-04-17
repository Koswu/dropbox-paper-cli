"""Tests for SharingInfo and MemberInfo dataclasses and SDK response mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

from dropbox_paper_cli.models.sharing import MemberInfo, SharingInfo


class TestMemberInfo:
    """MemberInfo creation and SDK mapping."""

    def test_create_member(self):
        member = MemberInfo(
            account_id="dbid:AAD123",
            display_name="Jane Doe",
            email="jane@example.com",
            access_type="owner",
        )
        assert member.display_name == "Jane Doe"
        assert member.access_type == "owner"

    def test_from_sdk(self):
        sdk_member = MagicMock()
        sdk_member.user.account_id = "dbid:AAD123"
        sdk_member.user.display_name = "Jane Doe"
        sdk_member.user.email = "jane@example.com"
        sdk_member.access_type._tag = "owner"

        member = MemberInfo.from_sdk(sdk_member)
        assert member.account_id == "dbid:AAD123"
        assert member.display_name == "Jane Doe"
        assert member.email == "jane@example.com"
        assert member.access_type == "owner"


class TestSharingInfo:
    """SharingInfo creation and SDK mapping."""

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

    def test_from_sdk(self):
        folder_meta = MagicMock()
        folder_meta.shared_folder_id = "sf:123"
        folder_meta.name = "Project Notes"
        folder_meta.path_display = "/Project Notes"

        members = [
            MemberInfo("dbid:1", "Jane", "jane@ex.com", "owner"),
        ]

        info = SharingInfo.from_sdk(folder_meta, members)
        assert info.shared_folder_id == "sf:123"
        assert info.name == "Project Notes"
        assert len(info.members) == 1

    def test_from_sdk_no_path(self):
        folder_meta = MagicMock()
        folder_meta.shared_folder_id = "sf:456"
        folder_meta.name = "Shared"
        folder_meta.path_display = None
        folder_meta.path_lower = "/shared"

        info = SharingInfo.from_sdk(folder_meta, [])
        assert info.path_display == "/shared"

    def test_default_empty_members(self):
        info = SharingInfo(shared_folder_id="sf:1", name="Test")
        assert info.members == []
