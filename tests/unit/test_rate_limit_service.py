"""RateLimitService token-bucket tests with fakeredis."""

import fakeredis.aioredis
import pytest

from llmops_gateway.services.rate_limit_service import RateLimitExceededError, RateLimitService


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


async def test_allows_requests_under_limit(fake_redis) -> None:
    service = RateLimitService(fake_redis, default_limit_per_minute=5, enabled=True)
    for _ in range(5):
        await service.check_and_increment("tenant-a", limit_per_minute=5)


async def test_blocks_when_bucket_empty(fake_redis) -> None:
    service = RateLimitService(fake_redis, default_limit_per_minute=2, enabled=True)
    await service.check_and_increment("tenant-b", limit_per_minute=2)
    await service.check_and_increment("tenant-b", limit_per_minute=2)

    with pytest.raises(RateLimitExceededError) as exc_info:
        await service.check_and_increment("tenant-b", limit_per_minute=2)

    assert exc_info.value.retry_after_seconds > 0


async def test_disabled_service_is_noop(fake_redis) -> None:
    service = RateLimitService(fake_redis, default_limit_per_minute=1, enabled=False)
    for _ in range(10):
        await service.check_and_increment("tenant-c")


async def test_per_tenant_isolation(fake_redis) -> None:
    service = RateLimitService(fake_redis, default_limit_per_minute=1, enabled=True)
    await service.check_and_increment("tenant-x", limit_per_minute=1)
    await service.check_and_increment("tenant-y", limit_per_minute=1)

    with pytest.raises(RateLimitExceededError):
        await service.check_and_increment("tenant-x", limit_per_minute=1)
