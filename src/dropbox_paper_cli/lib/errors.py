"""AppError hierarchy, ExitCode enum, and machine-readable error code constants."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """CLI exit codes per the CLI contract."""

    SUCCESS = 0
    GENERAL_ERROR = 1
    AUTH_ERROR = 2
    NOT_FOUND = 3
    VALIDATION_ERROR = 4
    NETWORK_ERROR = 5
    PERMISSION_ERROR = 6


class AppError(Exception):
    """Base application error with a machine-readable code and exit code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "GENERAL_FAILURE",
        exit_code: ExitCode = ExitCode.GENERAL_ERROR,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


class AuthenticationError(AppError):
    """Authentication failure — exit code 2."""

    def __init__(self, message: str, *, code: str = "AUTH_REQUIRED") -> None:
        super().__init__(message, code=code, exit_code=ExitCode.AUTH_ERROR)


class NotFoundError(AppError):
    """Resource not found — exit code 3."""

    def __init__(self, message: str, *, code: str = "NOT_FOUND") -> None:
        super().__init__(message, code=code, exit_code=ExitCode.NOT_FOUND)


class ValidationError(AppError):
    """Invalid input — exit code 4."""

    def __init__(self, message: str, *, code: str = "INVALID_INPUT") -> None:
        super().__init__(message, code=code, exit_code=ExitCode.VALIDATION_ERROR)


class NetworkError(AppError):
    """Network or API error — exit code 5."""

    def __init__(self, message: str, *, code: str = "NETWORK_ERROR") -> None:
        super().__init__(message, code=code, exit_code=ExitCode.NETWORK_ERROR)


class PermissionError(AppError):
    """Insufficient permissions — exit code 6."""

    def __init__(self, message: str, *, code: str = "PERMISSION_DENIED") -> None:
        super().__init__(message, code=code, exit_code=ExitCode.PERMISSION_ERROR)
