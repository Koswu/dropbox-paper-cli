"""@with_retry decorator: async exponential backoff for transient HTTP errors.

Catches httpx status errors (429/500/503), connection and timeout errors.
Respects the Retry-After header on 429 responses.  After all retries are
exhausted, transport-level errors are wrapped as ``NetworkError``.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

import httpx

from dropbox_paper_cli.lib.errors import NetworkError

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger("dropbox_paper_cli.lib.retry")

# Errors that should trigger a retry (R-005)
_RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
)


def _get_retry_after(exc: BaseException) -> float | None:
    """Extract Retry-After seconds from an HTTPStatusError's response."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        header = exc.response.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
    return None


def _is_retryable(exc: BaseException) -> bool:
    """Check if an exception warrants a retry."""
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 503)
    return False


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Callable[[F], F]:
    """Decorator that retries an async function on transient errors with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (not counting the initial call).
        base_delay: Base delay in seconds. Actual delay = base_delay * 2^attempt.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if not _is_retryable(exc):
                        raise
                    if attempt == max_retries:
                        # Wrap transport-level errors as NetworkError for callers
                        if isinstance(exc, _RETRYABLE_EXCEPTIONS):
                            raise NetworkError(
                                f"Network error after {max_retries} retries: {exc}"
                            ) from exc
                        if isinstance(exc, httpx.HTTPStatusError):
                            code = exc.response.status_code
                            raise NetworkError(
                                f"Server error (HTTP {code}) after {max_retries} retries"
                            ) from exc
                        raise
                    # Use Retry-After header if present, else exponential backoff
                    retry_after = _get_retry_after(exc)
                    delay = retry_after if retry_after is not None else base_delay * (2**attempt)
                    logger.debug(
                        "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                        attempt + 1,
                        max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
            # Should not reach here, but just in case
            assert last_exception is not None
            raise last_exception

        return cast(F, wrapper)

    return decorator
