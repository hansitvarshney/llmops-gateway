"""CacheService: dual-layer lookup/backfill coordination + request
coalescing, using fakeredis for the lock and simple in-memory fake
CacheStore layers for the two cache tiers."""

import asyncio
from datetime import UTC, datetime

import fakeredis

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.interfaces.cache_store import CacheStore
from llmops_gateway.domain.value_objects.cache_status import CacheStatus
from llmops_gateway.services.cache_service import CacheService


class _InMemoryCacheStore(CacheStore):
    def __init__(self) -> None:
        self.data: dict[str, ChatResponse] = {}
        self.get_calls = 0
        self.set_calls = 0

    def _key(self, request: ChatRequest, tenant_id: str) -> str:
        fingerprint = f"{request.canonical_prompt()}:{request.params_fingerprint()}"
        return f"{tenant_id}:{request.model}:{fingerprint}"

    async def get(self, request: ChatRequest, *, tenant_id: str) -> ChatResponse | None:
        self.get_calls += 1
        return self.data.get(self._key(request, tenant_id))

    async def set(self, request: ChatRequest, response: ChatResponse, *, tenant_id: str) -> None:
        self.set_calls += 1
        self.data[self._key(request, tenant_id)] = response


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


def _service() -> tuple[CacheService, _InMemoryCacheStore, _InMemoryCacheStore]:
    exact = _InMemoryCacheStore()
    semantic = _InMemoryCacheStore()
    redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    service = CacheService(
        exact,
        semantic,
        redis_client,
        coalescing_wait_seconds=0.3,
        coalescing_poll_interval_seconds=0.02,
    )
    return service, exact, semantic


async def test_lookup_returns_bypassed_without_touching_stores() -> None:
    service, exact, semantic = _service()
    result, status = await service.lookup(_request(cache_bypass=True), tenant_id="t1")
    assert result is None
    assert status == CacheStatus.BYPASSED
    assert exact.get_calls == 0
    assert semantic.get_calls == 0


async def test_lookup_miss_when_both_layers_empty() -> None:
    service, _, _ = _service()
    result, status = await service.lookup(_request(), tenant_id="t1")
    assert result is None
    assert status == CacheStatus.MISS


async def test_lookup_exact_hit_short_circuits_semantic_layer() -> None:
    service, exact, semantic = _service()
    request = _request()
    await exact.set(request, _response("cached"), tenant_id="t1")

    result, status = await service.lookup(request, tenant_id="t1")
    assert status == CacheStatus.EXACT_HIT
    assert result is not None
    assert result.message.content == "cached"
    assert semantic.get_calls == 0


async def test_lookup_semantic_hit_backfills_exact_layer() -> None:
    service, exact, semantic = _service()
    request = _request()
    await semantic.set(request, _response("semantic answer"), tenant_id="t1")

    result, status = await service.lookup(request, tenant_id="t1")
    assert status == CacheStatus.SEMANTIC_HIT
    assert result is not None
    assert result.message.content == "semantic answer"

    await asyncio.sleep(0.05)  # let the fire-and-forget L1 backfill task run
    backfilled = await exact.get(request, tenant_id="t1")
    assert backfilled is not None
    assert backfilled.message.content == "semantic answer"


async def test_backfill_writes_through_both_layers() -> None:
    service, exact, semantic = _service()
    request = _request()
    await service.backfill(request, _response("fresh"), tenant_id="t1")
    assert exact.set_calls == 1
    assert semantic.set_calls == 1


async def test_coalescing_lock_is_exclusive_per_request() -> None:
    service, _, _ = _service()
    request = _request()

    won_first = await service.acquire_coalescing_lock(request, tenant_id="t1")
    won_second = await service.acquire_coalescing_lock(request, tenant_id="t1")
    assert won_first is True
    assert won_second is False

    await service.release_coalescing_lock(request, tenant_id="t1")
    won_third = await service.acquire_coalescing_lock(request, tenant_id="t1")
    assert won_third is True


async def test_coalescing_lock_is_independent_per_tenant() -> None:
    service, _, _ = _service()
    request = _request()

    won_tenant_a = await service.acquire_coalescing_lock(request, tenant_id="tenant-a")
    won_tenant_b = await service.acquire_coalescing_lock(request, tenant_id="tenant-b")
    assert won_tenant_a is True
    assert won_tenant_b is True


async def test_wait_for_coalesced_result_returns_once_winner_writes_it() -> None:
    service, exact, _ = _service()
    request = _request()

    async def _winner_writes_after_delay() -> None:
        await asyncio.sleep(0.05)
        await exact.set(request, _response("winner result"), tenant_id="t1")

    asyncio.create_task(_winner_writes_after_delay())
    result = await service.wait_for_coalesced_result(request, tenant_id="t1")
    assert result is not None
    assert result.message.content == "winner result"


async def test_wait_for_coalesced_result_times_out_to_none() -> None:
    service, _, _ = _service()
    result = await service.wait_for_coalesced_result(_request(), tenant_id="t1")
    assert result is None
