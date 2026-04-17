"""Tests for @with_retry decorator: exponential backoff, retryable errors, max retries."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dropbox_paper_cli.lib.retry import with_retry


class TestRetryOnSuccess:
    """Functions that succeed on first call are not retried."""

    def test_no_retry_on_success(self):
        mock_fn = MagicMock(return_value="ok")
        decorated = with_retry(max_retries=3)(mock_fn)
        result = decorated()
        assert result == "ok"
        assert mock_fn.call_count == 1


class TestRetryOnTransientError:
    """Transient errors (HttpError, ConnectionError) trigger retries."""

    def test_retries_on_connection_error(self):
        mock_fn = MagicMock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "ok"])
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = decorated()
        assert result == "ok"
        assert mock_fn.call_count == 3

    def test_retries_on_timeout_error(self):
        mock_fn = MagicMock(side_effect=[TimeoutError("timeout"), "ok"])
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        result = decorated()
        assert result == "ok"
        assert mock_fn.call_count == 2


class TestRetryExhaustion:
    """When max retries are exhausted, the last exception is raised."""

    def test_raises_after_max_retries(self):
        mock_fn = MagicMock(side_effect=ConnectionError("persistent fail"))
        decorated = with_retry(max_retries=2, base_delay=0.01)(mock_fn)
        with pytest.raises(ConnectionError, match="persistent fail"):
            decorated()
        # 1 initial + 2 retries = 3 calls
        assert mock_fn.call_count == 3


class TestRetryNonRetryableError:
    """Non-retryable errors (ValueError, KeyError) are raised immediately."""

    def test_no_retry_on_value_error(self):
        mock_fn = MagicMock(side_effect=ValueError("bad input"))
        decorated = with_retry(max_retries=3, base_delay=0.01)(mock_fn)
        with pytest.raises(ValueError, match="bad input"):
            decorated()
        assert mock_fn.call_count == 1


class TestRetryExponentialBackoff:
    """Delays increase exponentially with each retry."""

    @patch("dropbox_paper_cli.lib.retry.time.sleep")
    def test_exponential_delays(self, mock_sleep):
        mock_fn = MagicMock(
            side_effect=[ConnectionError(), ConnectionError(), ConnectionError(), "ok"]
        )
        decorated = with_retry(max_retries=3, base_delay=1.0)(mock_fn)
        decorated()
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(delays) == 3
        # Delays should be 1, 2, 4 (base * 2^attempt)
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)
        assert delays[2] == pytest.approx(4.0)
