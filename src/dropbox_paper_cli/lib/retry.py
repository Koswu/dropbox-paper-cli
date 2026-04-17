"""@with_retry decorator: exponential backoff for transient Dropbox API errors."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar, cast

import dropbox.exceptions

F = TypeVar("F", bound=Callable[..., Any])

# Errors that should trigger a retry
_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _is_retryable(exc: BaseException) -> bool:
    """Check if an exception is retryable."""
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    if isinstance(exc, dropbox.exceptions.HttpError):
        return True
    return bool(isinstance(exc, dropbox.exceptions.InternalServerError))


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    verbose_stream: Any = None,
) -> Callable[[F], F]:
    """Decorator that retries a function on transient errors with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (not counting the initial call).
        base_delay: Base delay in seconds. Actual delay = base_delay * 2^attempt.
        verbose_stream: Stream for verbose logging (stderr). None disables logging.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if not _is_retryable(exc):
                        raise
                    if attempt == max_retries:
                        raise
                    delay = base_delay * (2**attempt)
                    if verbose_stream:
                        print(
                            f"[retry] Attempt {attempt + 1}/{max_retries} failed: {exc}. "
                            f"Retrying in {delay:.1f}s...",
                            file=verbose_stream,
                        )
                    time.sleep(delay)
            # Should not reach here, but just in case
            assert last_exception is not None
            raise last_exception

        return cast(F, wrapper)

    return decorator
