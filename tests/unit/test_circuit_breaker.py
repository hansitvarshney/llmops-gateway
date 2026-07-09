"""Circuit breaker + backoff unit tests — no network, no real providers."""

import asyncio

from llmops_gateway.providers.base import CircuitBreaker, CircuitState, compute_backoff_delay


async def test_circuit_closed_by_default() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
    assert await breaker.allow_request() is True
    assert breaker.state is CircuitState.CLOSED


async def test_circuit_opens_after_threshold_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
    await breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED
    await breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert await breaker.allow_request() is False


async def test_circuit_half_opens_after_cooldown() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    await breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    await asyncio.sleep(0.06)
    assert breaker.state is CircuitState.HALF_OPEN
    assert await breaker.allow_request() is True


async def test_circuit_closes_on_success_after_half_open_probe() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    await breaker.record_failure()
    await asyncio.sleep(0.06)
    assert breaker.state is CircuitState.HALF_OPEN
    await breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


async def test_circuit_reopens_if_half_open_probe_fails() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    await breaker.record_failure()
    await asyncio.sleep(0.06)
    assert breaker.state is CircuitState.HALF_OPEN
    await breaker.record_failure()
    assert breaker.state is CircuitState.OPEN


def test_compute_backoff_delay_honors_retry_after() -> None:
    assert compute_backoff_delay(0, retry_after_seconds=12.5) == 12.5


def test_compute_backoff_delay_grows_exponentially() -> None:
    d0 = compute_backoff_delay(0, jitter_seconds=0)
    d1 = compute_backoff_delay(1, jitter_seconds=0)
    d2 = compute_backoff_delay(2, jitter_seconds=0)
    assert d0 < d1 < d2


def test_compute_backoff_delay_caps_at_max() -> None:
    delay = compute_backoff_delay(20, max_seconds=5.0, jitter_seconds=0)
    assert delay == 5.0
