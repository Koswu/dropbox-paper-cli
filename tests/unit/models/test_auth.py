"""Tests for AuthToken dataclass: validation, expiry check, JSON serialization."""

from __future__ import annotations

import time

import pytest

from dropbox_paper_cli.models.auth import AuthToken


class TestAuthTokenCreation:
    """AuthToken stores OAuth2 credentials with validation."""

    def test_valid_token(self):
        token = AuthToken(
            access_token="sl.access123",
            refresh_token="refresh456",
            expires_at=time.time() + 3600,
            account_id="dbid:AADxxxxxx",
        )
        assert token.access_token == "sl.access123"
        assert token.refresh_token == "refresh456"
        assert token.account_id == "dbid:AADxxxxxx"
        assert token.token_type == "bearer"

    def test_optional_uid(self):
        token = AuthToken(
            access_token="sl.a",
            refresh_token="r",
            expires_at=time.time() + 3600,
            account_id="dbid:AAD",
            uid="12345",
        )
        assert token.uid == "12345"

    def test_uid_default_none(self):
        token = AuthToken(
            access_token="sl.a",
            refresh_token="r",
            expires_at=time.time() + 3600,
            account_id="dbid:AAD",
        )
        assert token.uid is None


class TestAuthTokenValidation:
    """AuthToken validates required fields on creation."""

    def test_empty_access_token_raises(self):
        with pytest.raises(ValueError, match="access_token"):
            AuthToken(
                access_token="",
                refresh_token="r",
                expires_at=time.time() + 3600,
                account_id="dbid:AAD",
            )

    def test_empty_refresh_token_raises(self):
        with pytest.raises(ValueError, match="refresh_token"):
            AuthToken(
                access_token="sl.a",
                refresh_token="",
                expires_at=time.time() + 3600,
                account_id="dbid:AAD",
            )

    def test_empty_account_id_raises(self):
        with pytest.raises(ValueError, match="account_id"):
            AuthToken(
                access_token="sl.a",
                refresh_token="r",
                expires_at=time.time() + 3600,
                account_id="",
            )

    def test_non_positive_expires_at_raises(self):
        with pytest.raises(ValueError, match="expires_at"):
            AuthToken(
                access_token="sl.a",
                refresh_token="r",
                expires_at=-1.0,
                account_id="dbid:AAD",
            )


class TestAuthTokenExpiry:
    """is_expired checks whether the access token has expired."""

    def test_not_expired(self):
        token = AuthToken(
            access_token="sl.a",
            refresh_token="r",
            expires_at=time.time() + 3600,
            account_id="dbid:AAD",
        )
        assert token.is_expired is False

    def test_expired(self):
        token = AuthToken(
            access_token="sl.a",
            refresh_token="r",
            expires_at=time.time() - 100,
            account_id="dbid:AAD",
        )
        assert token.is_expired is True


class TestAuthTokenSerialization:
    """AuthToken serializes to/from JSON dict for file storage."""

    def test_to_dict(self):
        token = AuthToken(
            access_token="sl.access",
            refresh_token="refresh",
            expires_at=1700000000.0,
            account_id="dbid:AAD",
            uid="123",
        )
        d = token.to_dict()
        assert d["access_token"] == "sl.access"
        assert d["refresh_token"] == "refresh"
        assert d["expires_at"] == 1700000000.0
        assert d["account_id"] == "dbid:AAD"
        assert d["uid"] == "123"
        assert d["token_type"] == "bearer"

    def test_from_dict(self):
        d = {
            "access_token": "sl.access",
            "refresh_token": "refresh",
            "expires_at": 1700000000.0,
            "account_id": "dbid:AAD",
            "uid": "123",
            "token_type": "bearer",
        }
        token = AuthToken.from_dict(d)
        assert token.access_token == "sl.access"
        assert token.account_id == "dbid:AAD"
        assert token.uid == "123"

    def test_roundtrip(self):
        original = AuthToken(
            access_token="sl.rt",
            refresh_token="ref_rt",
            expires_at=1700000000.0,
            account_id="dbid:RT",
        )
        restored = AuthToken.from_dict(original.to_dict())
        assert restored.access_token == original.access_token
        assert restored.refresh_token == original.refresh_token
        assert restored.expires_at == original.expires_at
        assert restored.account_id == original.account_id
