"""SharingInfo and MemberInfo dataclasses with API response mapping."""

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
    def from_api(cls, data: dict[str, Any]) -> MemberInfo:
        """Create from Dropbox API JSON member entry.

        API structure: ``{"user": {"account_id": ..., "display_name": ..., "email": ...}, "access_type": {".tag": "..."}}``
        """
        user = data["user"]
        access_type_raw = data.get("access_type", {})
        access_type = (
            access_type_raw.get(".tag", str(access_type_raw))
            if isinstance(access_type_raw, dict)
            else str(access_type_raw)
        )
        return cls(
            account_id=user["account_id"],
            display_name=user.get("display_name", ""),
            email=user.get("email", ""),
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
    def from_api(cls, data: dict[str, Any], members: list[MemberInfo] | None = None) -> SharingInfo:
        """Create from a Dropbox API shared folder metadata response."""
        return cls(
            shared_folder_id=data["shared_folder_id"],
            name=data["name"],
            path_display=data.get("path_display") or data.get("path_lower"),
            members=members or [],
        )
