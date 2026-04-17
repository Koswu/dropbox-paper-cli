"""SharingInfo and MemberInfo dataclasses with SDK response mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemberInfo:
    """A member of a shared folder with role information."""

    account_id: str
    display_name: str
    email: str
    access_type: str  # "owner", "editor", "viewer", "viewer_no_comment"

    @classmethod
    def from_sdk(cls, member: Any) -> MemberInfo:
        """Create from a Dropbox SDK UserMembershipInfo object."""
        user = member.user
        access_type = (
            str(member.access_type._tag)
            if hasattr(member.access_type, "_tag")
            else str(member.access_type)
        )
        return cls(
            account_id=user.account_id,
            display_name=user.display_name,
            email=user.email,
            access_type=access_type,
        )


@dataclass
class SharingInfo:
    """Sharing metadata for a shared folder."""

    shared_folder_id: str
    name: str
    path_display: str | None = None
    members: list[MemberInfo] = field(default_factory=list)

    @classmethod
    def from_sdk(cls, folder_meta: Any, members: list[MemberInfo] | None = None) -> SharingInfo:
        """Create from a Dropbox SDK SharedFolderMetadata object."""
        return cls(
            shared_folder_id=folder_meta.shared_folder_id,
            name=folder_meta.name,
            path_display=getattr(folder_meta, "path_display", None)
            or getattr(folder_meta, "path_lower", None),
            members=members or [],
        )
