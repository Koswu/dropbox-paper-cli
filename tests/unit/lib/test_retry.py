"""Tests for async @with_retry decorator: exponential backoff, httpx errors, Retry-After."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from dropbox_paper_cli.lib.errors import NetworkError
from dropbox_paper_cli.lib.retry import with_retry


def _make_http_status_error(
    status_code: int, retry_after: str | None = None
) -> httpx.HTTPStatusError:
    """Build an HTTPStatusError with optional Retry-After header."""
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = httpx.Response(
        status_code=status_code,
        headers=headers,
        request=httpx.Request("POST", "https://api.dropboxapi.com/2/test"),
    )
    return httpx.HTTPStatusError(
        message=f"HTTP {status_code}",
        request=response.request,
        response=response,
    )


class TestRetryOnSuccess:
    """Functions that succeed on first call are not retried."""

    async def test_no_retry_on_success(self):
        mock_fn = AsyncMock(return_value="ok")
        decorated = with_retry(max_retries=3)(mock_fn)
        result = await decorated()
        assert result == "ok"
        assert mock_fn.call_count == 1


class TestRetryOnTransientError:
    """Transient httpx errors trigger retries."""

    async def test_retries_on_connect_error(self):
        mock_fn = AsyncMock(
            side_effect=[httpx.ConnectError("fail"), httpx.ConnectError("fail"), "ok"]
        )
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "ok"
        assert mock_fn.call_count == 3

    async def test_retries_on_read_timeout(self):
        mock_fn = AsyncMock(side_effect=[httpx.ReadTimeout("timeout"), "ok"])
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "ok"
        assert mock_fn.call_count == 2

    async def test_retries_on_connect_timeout(self):
        mock_fn = AsyncMock(side_effect=[httpx.ConnectTimeout("timeout"), "ok"])
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "ok"
        assert mock_fn.call_count == 2

    async def test_retries_on_429_status(self):
        mock_fn = AsyncMock(side_effect=[_make_http_status_error(429), "ok"])
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "ok"
        assert mock_fn.call_count == 2

    async def test_retries_on_500_status(self):
        mock_fn = AsyncMock(side_effect=[_make_http_status_error(500), "ok"])
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "ok"
        assert mock_fn.call_count == 2

    async def test_retries_on_503_status(self):
        mock_fn = AsyncMock(side_effect=[_make_http_status_error(503), "ok"])
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = await decorated()
        assert result == "ok"
        assert mock_fn.call_count == 2


class TestRetryExhaustion:
    """When max retries are exhausted, transport errors are wrapped as NetworkError."""

    async def test_raises_network_error_after_max_retries(self):
        mock_fn = AsyncMock(side_effect=httpx.ConnectError("persistent fail"))
        decorated = with_retry(max_retries=2, base_delay=0.01)(mock_fn)
        with pytest.raises(NetworkError, match="Network error after 2 retries"):
            await decorated()
        # 1 initial + 2 retries = 3 calls
        assert mock_fn.call_count == 3

    async def test_raises_network_error_after_server_errors(self):
        mock_fn = AsyncMock(
            side_effect=[
                _make_http_status_error(500),
                _make_http_status_error(500),
                _make_http_status_error(500),
            ]
        )
        decorated = with_retry(max_retries=2, base_delay=0.01)(mock_fn)
        with pytest.raises(NetworkError, match="Server error \\(HTTP 500\\) after 2 retries"):
            await decorated()
        assert mock_fn.call_count == 3


class TestRetryNonRetryableError:
    """Non-retryable errors are raised immediately without retry."""

    async def test_no_retry_on_value_error(self):
        mock_fn = AsyncMock(side_effect=ValueError("bad input"))
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        with pytest.raises(ValueError, match="bad input"):
            await decorated()
        assert mock_fn.call_count == 1

    async def test_no_retry_on_404_status(self):
        """Non-retryable HTTP status codes (e.g. 404) are not retried."""
        mock_fn = AsyncMock(side_effect=_make_http_status_error(404))
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        with pytest.raises(httpx.HTTPStatusError):
            await decorated()
        assert mock_fn.call_count == 1


class TestRetryExponentialBackoff:
    """Delays increase exponentially with each retry."""

    @patch("dropbox_paper_cli.lib.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_delays(self, mock_sleep):
        mock_fn = AsyncMock(
            side_effect=[
                httpx.ConnectError(""),
                httpx.ConnectError(""),
                httpx.ConnectError(""),
                "ok",
            ]
        )
        decorated = with_retry(max_retries=3, base_delay=1.0)(mock_fn)
        await decorated()
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(delays) == 3
        # Delays should be 1, 2, 4 (base * 2^attempt)
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)
        assert delays[2] == pytest.approx(4.0)


class TestRetryAfterHeader:
    """429 with Retry-After header uses the header value as delay."""

    @patch("dropbox_paper_cli.lib.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_uses_retry_after_header(self, mock_sleep):
        error_with_header = _make_http_status_error(429, retry_after="5")
        mock_fn = AsyncMock(side_effect=[error_with_header, "ok"])
        decorated = with_retry(max_retries=3, base_delay=1.0)(mock_fn)
        await decorated()
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(delays) == 1
        assert delays[0] == pytest.approx(5.0)
