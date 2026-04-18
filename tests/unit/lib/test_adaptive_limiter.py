"""Tests for the AdaptiveLimiter concurrency controller."""

from __future__ import annotations

import asyncio

import pytest

from dropbox_paper_cli.lib.adaptive_limiter import AdaptiveLimiter


@pytest.fixture
def limiter() -> AdaptiveLimiter:
    return AdaptiveLimiter(initial=5, minimum=2, maximum=50)


class TestInit:
    def test_defaults(self, limiter: AdaptiveLimiter) -> None:
        assert limiter.limit == 5
        assert limiter.active == 0
        assert limiter.ceiling is None

    def test_initial_clamped_to_minimum(self) -> None:
        lim = AdaptiveLimiter(initial=1, minimum=3, maximum=10)
        assert lim.limit == 3


class TestContextManager:
    @pytest.mark.asyncio
    async def test_acquire_release(self, limiter: AdaptiveLimiter) -> None:
        async with limiter:
            assert limiter.active == 1
        assert limiter.active == 0

    @pytest.mark.asyncio
    async def test_concurrent_limit_respected(self) -> None:
        limiter = AdaptiveLimiter(initial=2, minimum=1, maximum=10)
        max_concurrent = 0
        lock = asyncio.Lock()

        async def worker() -> None:
            nonlocal max_concurrent
            async with limiter:
                async with lock:
                    max_concurrent = max(max_concurrent, limiter.active)
                await asyncio.sleep(0.01)

        await asyncio.gather(*[worker() for _ in range(6)])
        assert max_concurrent <= 2


class TestOnSuccess:
    @pytest.mark.asyncio
    async def test_ramps_up_by_2_when_exploring(self, limiter: AdaptiveLimiter) -> None:
        """No ceiling → ramp step = 2."""
        assert limiter.limit == 5
        await limiter.on_success()
        assert limiter.limit == 7
        await limiter.on_success()
        assert limiter.limit == 9

    @pytest.mark.asyncio
    async def test_ramps_up_by_1_near_ceiling(self) -> None:
        """With ceiling → ramp step = 1, target = ceiling * 0.8."""
        limiter = AdaptiveLimiter(initial=5, minimum=2, maximum=50)
        # Simulate finding ceiling at 10
        limiter._ceiling = 10  # target = int(10 * 0.8) = 8
        limiter._limit = 5
        await limiter.on_success()
        assert limiter.limit == 6  # +1 cautious step
        await limiter.on_success()
        assert limiter.limit == 7
        await limiter.on_success()
        assert limiter.limit == 8  # = target, stops here
        await limiter.on_success()
        assert limiter.limit == 8  # no more increase

    @pytest.mark.asyncio
    async def test_does_not_exceed_max(self) -> None:
        limiter = AdaptiveLimiter(initial=48, minimum=2, maximum=50)
        await limiter.on_success()
        assert limiter.limit == 50
        await limiter.on_success()
        assert limiter.limit == 50


class TestOnRateLimit:
    @pytest.mark.asyncio
    async def test_sets_ceiling_and_reduces(self, limiter: AdaptiveLimiter) -> None:
        assert limiter.limit == 5
        await limiter.on_rate_limit()
        assert limiter.ceiling == 5
        # 5 * 0.7 = 3.5 → int(3.5) = 3
        assert limiter.limit == 3

    @pytest.mark.asyncio
    async def test_does_not_go_below_minimum(self) -> None:
        limiter = AdaptiveLimiter(initial=2, minimum=2, maximum=50)
        await limiter.on_rate_limit()
        assert limiter.limit == 2  # clamped to min

    @pytest.mark.asyncio
    async def test_repeated_rate_limits_lower_ceiling(self) -> None:
        limiter = AdaptiveLimiter(initial=10, minimum=2, maximum=50)
        await limiter.on_rate_limit()
        assert limiter.ceiling == 10
        assert limiter.limit == 7  # int(10 * 0.7)
        await limiter.on_rate_limit()
        assert limiter.ceiling == 7
        assert limiter.limit == 4  # int(7 * 0.7) = 4


class TestOnError:
    @pytest.mark.asyncio
    async def test_reduces_by_one(self, limiter: AdaptiveLimiter) -> None:
        assert limiter.limit == 5
        await limiter.on_error()
        assert limiter.limit == 4

    @pytest.mark.asyncio
    async def test_does_not_go_below_minimum(self) -> None:
        limiter = AdaptiveLimiter(initial=2, minimum=2, maximum=50)
        await limiter.on_error()
        assert limiter.limit == 2


class TestFullCycleIntegration:
    @pytest.mark.asyncio
    async def test_explore_hit_ceiling_stabilise(self) -> None:
        """Simulates: ramp up → hit 429 → stabilise at 80% of ceiling."""
        limiter = AdaptiveLimiter(initial=3, minimum=2, maximum=50)

        # Ramp up with successes
        for _ in range(4):
            await limiter.on_success()
        assert limiter.limit == 11  # 3 + 4*2

        # Hit rate limit
        await limiter.on_rate_limit()
        assert limiter.ceiling == 11
        assert limiter.limit == 7  # int(11 * 0.7)

        # Recover: ramps up cautiously towards int(11 * 0.8) = 8
        await limiter.on_success()
        assert limiter.limit == 8  # 7 + 1
        await limiter.on_success()
        assert limiter.limit == 8  # already at target, no increase

    @pytest.mark.asyncio
    async def test_dynamic_limit_unblocks_waiters(self) -> None:
        """Workers waiting on a full limiter proceed when limit increases."""
        limiter = AdaptiveLimiter(initial=1, minimum=1, maximum=10)
        entered = asyncio.Event()
        done = asyncio.Event()

        async def waiting_worker() -> None:
            async with limiter:
                entered.set()
                await done.wait()

        async def blocker() -> None:
            async with limiter:
                # While we hold the slot, start the waiting worker
                task = asyncio.create_task(waiting_worker())
                await asyncio.sleep(0.01)
                assert not entered.is_set()  # waiting_worker is blocked
                # Increase limit to unblock
                await limiter.on_success()
                await asyncio.sleep(0.01)
                assert entered.is_set()  # now unblocked
                done.set()
                await task

        await blocker()
