"""Adaptive concurrency limiter that discovers and respects API rate limits.

Starts at a low concurrency and ramps up until hitting a 429/rate-limit error.
Once the ceiling is found, stabilises at ~80% of that ceiling to avoid
oscillation.  Uses asyncio.Condition for dynamic limit adjustment.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("dropbox_paper_cli.lib.adaptive_limiter")

_DEFAULT_INITIAL = 5
_DEFAULT_MIN = 2
_DEFAULT_MAX = 50
_BACKOFF_FACTOR = 0.7
_CEILING_MARGIN = 0.8
_RAMP_STEP_EXPLORING = 2  # fast ramp before ceiling is known
_RAMP_STEP_CAUTIOUS = 1  # slow ramp near ceiling


class AdaptiveLimiter:
    """Context-manager-based concurrency limiter with dynamic adjustment.

    Usage::

        limiter = AdaptiveLimiter(initial=5)

        async def worker():
            async with limiter:
                result = await do_work()
            await limiter.on_success()   # slowly increase limit

        # On rate-limit error:
        await limiter.on_rate_limit()    # reduce limit, record ceiling
    """

    def __init__(
        self,
        initial: int = _DEFAULT_INITIAL,
        *,
        minimum: int = _DEFAULT_MIN,
        maximum: int = _DEFAULT_MAX,
    ) -> None:
        self._limit = max(initial, minimum)
        self._min = minimum
        self._max = maximum
        self._ceiling: int | None = None
        self._active = 0
        self._condition = asyncio.Condition()

    @property
    def limit(self) -> int:
        """Current concurrency limit."""
        return self._limit

    @property
    def active(self) -> int:
        """Number of currently active tasks."""
        return self._active

    @property
    def ceiling(self) -> int | None:
        """Discovered rate-limit ceiling, or None if not yet hit."""
        return self._ceiling

    async def __aenter__(self) -> AdaptiveLimiter:
        async with self._condition:
            while self._active >= self._limit:
                await self._condition.wait()
            self._active += 1
        return self

    async def __aexit__(self, *_args: object) -> None:
        async with self._condition:
            self._active -= 1
            self._condition.notify()

    async def on_success(self) -> None:
        """Call after a request succeeds to potentially increase concurrency."""
        async with self._condition:
            if self._ceiling is not None:
                target = int(self._ceiling * _CEILING_MARGIN)
                step = _RAMP_STEP_CAUTIOUS
            else:
                target = self._max
                step = _RAMP_STEP_EXPLORING

            if self._limit < target:
                old = self._limit
                self._limit = min(self._limit + step, target)
                if self._limit != old:
                    logger.debug("Concurrency: %d → %d", old, self._limit)
                    self._condition.notify_all()

    async def on_rate_limit(self) -> None:
        """Call when a 429 / rate-limit error is detected."""
        async with self._condition:
            old = self._limit
            self._ceiling = self._limit
            self._limit = max(int(self._limit * _BACKOFF_FACTOR), self._min)
            logger.debug(
                "Rate limit hit! Concurrency: %d → %d (ceiling=%d)",
                old,
                self._limit,
                self._ceiling,
            )

    async def on_error(self) -> None:
        """Call on a non-rate-limit error to mildly reduce concurrency."""
        async with self._condition:
            if self._limit > self._min:
                old = self._limit
                self._limit = max(self._limit - 1, self._min)
                logger.debug("Error, concurrency: %d → %d", old, self._limit)
