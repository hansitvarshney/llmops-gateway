"""RedisExactCache tests against fakeredis (real Redis command semantics,
no real network/Docker required)."""

from datetime import UTC, datetime

import fakeredis
import pytest

from llmops_gateway.caching.redis_exact_cache import RedisExactCache
from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.value_objects.cache_status import CacheStatus


def _response(content: str = "hi") -> ChatResponse:
    return ChatResponse(
        id="1",
        model="gpt-4o",
        provider="openai",
        message=ChatMessage(role="assistant", content=content),
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.0,
        cache_status=CacheStatus.MISS,
        trace_id="t1",
        created_at=datetime.now(UTC),
        latency_ms=1.0,
    )


def _request(**overrides) -> ChatRequest:
    defaults = {"model": "gpt-4o", "messages": [ChatMessage(role="user", content="hi")]}
    defaults.update(overrides)
    return ChatRequest(**defaults)


@pytest.fixture
def redis_client():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


async def test_miss_returns_none(redis_client) -> None:
    cache = RedisExactCache(redis_client, ttl_seconds=60)
    assert await cache.get(_request(), tenant_id="t1") is None


async def test_set_then_get_returns_stamped_exact_hit(redis_client) -> None:
    cache = RedisExactCache(redis_client, ttl_seconds=60)
    request = _request()
    await cache.set(request, _response("hello"), tenant_id="t1")

    hit = await cache.get(request, tenant_id="t1")
    assert hit is not None
    assert hit.message.content == "hello"
    assert hit.cache_status == CacheStatus.EXACT_HIT


async def test_different_tenants_are_isolated(redis_client) -> None:
    cache = RedisExactCache(redis_client, ttl_seconds=60)
    request = _request()
    await cache.set(request, _response("hello"), tenant_id="tenant-a")

    assert await cache.get(request, tenant_id="tenant-b") is None
    assert await cache.get(request, tenant_id="tenant-a") is not None


async def test_different_params_are_not_conflated(redis_client) -> None:
    cache = RedisExactCache(redis_client, ttl_seconds=60)
    hot_request = _request(temperature=0.9)
    await cache.set(hot_request, _response("hello"), tenant_id="t1")

    cold_request = _request(temperature=0.1)
    assert await cache.get(cold_request, tenant_id="t1") is None


async def test_corrupt_entry_fails_closed_to_miss(redis_client) -> None:
    cache = RedisExactCache(redis_client, ttl_seconds=60)
    request = _request()
    key = RedisExactCache._key(request, "t1")
    await redis_client.set(key, "not valid json")

    assert await cache.get(request, tenant_id="t1") is None
