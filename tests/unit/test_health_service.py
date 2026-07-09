"""HealthService readiness probe tests."""

import fakeredis.aioredis
import pytest

from llmops_gateway.services.health_service import HealthService
from tests.conftest import _SQLiteDatabase


@pytest.fixture
async def health_deps():
    database = _SQLiteDatabase()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    class _FakeQdrant:
        async def get_collections(self):
            return object()

    service = HealthService(database, redis, _FakeQdrant())
    try:
        yield service, database, redis
    finally:
        await database.dispose()
        await redis.aclose()


async def test_readiness_ok_when_all_deps_healthy(health_deps) -> None:
    service, _, _ = health_deps
    report = await service.check_readiness()
    assert report.is_ready is True
    assert {dep.name for dep in report.dependencies} == {"postgres", "redis", "qdrant"}


async def test_readiness_degraded_when_redis_fails(health_deps) -> None:
    service, database, _ = health_deps

    class _BrokenRedis:
        async def ping(self):
            raise ConnectionError("redis down")

    broken = HealthService(database, _BrokenRedis(), service._qdrant)
    report = await broken.check_readiness()
    assert report.is_ready is False
    redis_dep = next(dep for dep in report.dependencies if dep.name == "redis")
    assert redis_dep.status == "error"
