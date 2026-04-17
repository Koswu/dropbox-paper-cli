"""AuthToken dataclass with validation, expiry check, and JSON serialization."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class AuthToken:
    """Represents persisted OAuth2 credentials.

    Validation rules:
    - access_token and refresh_token must be non-empty strings
    - expires_at must be a positive float
    - account_id must be a non-empty string
    """

    access_token: str
    refresh_token: str
    expires_at: float
    account_id: str
    uid: str | None = None
    token_type: str = "bearer"
    root_namespace_id: str | None = None
    home_namespace_id: str | None = None

    def __post_init__(self) -> None:
        """Validate required fields after dataclass initialization."""
        if not self.access_token:
            raise ValueError("access_token must be a non-empty string")
        if not self.refresh_token:
            raise ValueError("refresh_token must be a non-empty string")
        if self.expires_at <= 0:
            raise ValueError("expires_at must be a positive float")
        if not self.account_id:
            raise ValueError("account_id must be a non-empty string")

    @property
    def is_expired(self) -> bool:
        """Check whether the access token has expired."""
        return time.time() >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for file storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "account_id": self.account_id,
            "uid": self.uid,
            "token_type": self.token_type,
            "root_namespace_id": self.root_namespace_id,
            "home_namespace_id": self.home_namespace_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthToken:
        """Deserialize from a JSON-compatible dict."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            account_id=data["account_id"],
            uid=data.get("uid"),
            token_type=data.get("token_type", "bearer"),
            root_namespace_id=data.get("root_namespace_id"),
            home_namespace_id=data.get("home_namespace_id"),
        )
