"""Tests for AppError hierarchy, ExitCode enum, and error code constants."""

from __future__ import annotations

from dropbox_paper_cli.lib.errors import (
    AppError,
    AuthenticationError,
    ExitCode,
    NetworkError,
    NotFoundError,
    ValidationError,
)
from dropbox_paper_cli.lib.errors import (
    PermissionError as AppPermissionError,
)


class TestExitCode:
    """ExitCode enum maps exit codes 0–6 to descriptive names."""

    def test_success_is_zero(self):
        assert ExitCode.SUCCESS == 0

    def test_general_error_is_one(self):
        assert ExitCode.GENERAL_ERROR == 1

    def test_auth_error_is_two(self):
        assert ExitCode.AUTH_ERROR == 2

    def test_not_found_is_three(self):
        assert ExitCode.NOT_FOUND == 3

    def test_validation_error_is_four(self):
        assert ExitCode.VALIDATION_ERROR == 4

    def test_network_error_is_five(self):
        assert ExitCode.NETWORK_ERROR == 5

    def test_permission_error_is_six(self):
        assert ExitCode.PERMISSION_ERROR == 6

    def test_all_codes_present(self):
        assert len(ExitCode) == 7


class TestAppError:
    """AppError is the base exception with message, code, and exit_code."""

    def test_base_error_has_message(self):
        err = AppError("something went wrong")
        assert str(err) == "something went wrong"

    def test_base_error_has_code(self):
        err = AppError("fail", code="GENERAL_FAILURE")
        assert err.code == "GENERAL_FAILURE"

    def test_base_error_default_exit_code(self):
        err = AppError("fail")
        assert err.exit_code == ExitCode.GENERAL_ERROR

    def test_base_error_is_exception(self):
        assert issubclass(AppError, Exception)


class TestAuthenticationError:
    """AuthenticationError maps to exit code 2."""

    def test_exit_code(self):
        err = AuthenticationError("token expired", code="AUTH_EXPIRED")
        assert err.exit_code == ExitCode.AUTH_ERROR

    def test_is_app_error(self):
        assert issubclass(AuthenticationError, AppError)

    def test_code_stored(self):
        err = AuthenticationError("no token", code="AUTH_REQUIRED")
        assert err.code == "AUTH_REQUIRED"


class TestNotFoundError:
    """NotFoundError maps to exit code 3."""

    def test_exit_code(self):
        err = NotFoundError("file not found", code="NOT_FOUND")
        assert err.exit_code == ExitCode.NOT_FOUND


class TestValidationError:
    """ValidationError maps to exit code 4."""

    def test_exit_code(self):
        err = ValidationError("bad input", code="INVALID_INPUT")
        assert err.exit_code == ExitCode.VALIDATION_ERROR


class TestNetworkError:
    """NetworkError maps to exit code 5."""

    def test_exit_code(self):
        err = NetworkError("connection failed", code="NETWORK_ERROR")
        assert err.exit_code == ExitCode.NETWORK_ERROR


class TestPermissionError:
    """PermissionError maps to exit code 6."""

    def test_exit_code(self):
        err = AppPermissionError("access denied", code="PERMISSION_DENIED")
        assert err.exit_code == ExitCode.PERMISSION_ERROR
