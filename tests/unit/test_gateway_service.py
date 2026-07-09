"""GatewayService orchestration: cache hits must short-circuit before the
provider layer is ever touched and always report cost_usd=0 (no new spend);
cache misses call RoutingService, CostService, and fire-and-forget a cache
backfill afterward. Uses fake CacheService/RoutingService/CostService
doubles so this exercises orchestration logic in isolation — TracingService
persistence is exercised separately (see test_tracing_service.py) since
`database=None` here makes flush() a no-op fire-and-forget task."""

import asyncio
from datetime import UTC, datetime

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.value_objects.cache_status import CacheStatus
from llmops_gateway.services.gateway_service import GatewayService, StreamMetadata


class _FakeCacheService:
    def __init__(self, lookup_result=None) -> None:
        self.lookup_result = lookup_result or (None, CacheStatus.MISS)
        self.backfill_calls: list[tuple] = []
        self.lock_acquired = True

    async def lookup(self, request, *, tenant_id):
        return self.lookup_result

    async def backfill(self, request, response, *, tenant_id):
        self.backfill_calls.append((request, response, tenant_id))

    async def acquire_coalescing_lock(self, request, *, tenant_id):
        return self.lock_acquired

    async def release_coalescing_lock(self, request, *, tenant_id):
        return None

    async def wait_for_coalesced_result(self, request, *, tenant_id):
        return None


class _FakeCostService:
    def __init__(self, cost_usd: float = 0.42) -> None:
        self.cost_usd = cost_usd
        self.calls: list[tuple] = []

    async def calculate_cost_usd(self, model, usage):
        self.calls.append((model, usage))
        return self.cost_usd


class _FakeProvider:
    name = "openai"

    def __init__(self, usage: TokenUsage | None = None) -> None:
        self._usage = usage or TokenUsage(input_tokens=3, output_tokens=5)

    async def count_tokens(self, request, completion_text):
        return self._usage


class _FakeRoutingService:
    def __init__(self, complete_result=None, stream_chunks=None) -> None:
        self._complete_result = complete_result
        self._stream_chunks = stream_chunks or []
        self.complete_calls = 0
        self.stream_calls = 0

    async def complete(self, request):
        self.complete_calls += 1
        return self._complete_result

    async def stream(self, request, on_provider_selected=None):
        self.stream_calls += 1
        provider = _FakeProvider()
        for i, chunk in enumerate(self._stream_chunks):
            if i == 0 and on_provider_selected is not None:
                on_provider_selected(provider, request)
            yield chunk


def _response(content: str = "hi", provider: str = "openai", cost_usd: float = 0.0) -> ChatResponse:
    return ChatResponse(
        id="1",
        model="gpt-4o",
        provider=provider,
        message=ChatMessage(role="assistant", content=content),
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost_usd=cost_usd,
        cache_status=CacheStatus.MISS,
        trace_id="",
        created_at=datetime.now(UTC),
        latency_ms=0.0,
    )


def _request(**overrides) -> ChatRequest:
    defaults = {"model": "gpt-4o", "messages": [ChatMessage(role="user", content="hi")]}
    defaults.update(overrides)
    return ChatRequest(**defaults)


def _gateway(cache_service, routing, cost_service=None) -> GatewayService:
    return GatewayService(cache_service, routing, cost_service or _FakeCostService())


async def test_cache_hit_short_circuits_never_calls_routing_or_cost() -> None:
    cached = _response("cached answer", cost_usd=1.23)  # cost from when it was first generated
    cache_service = _FakeCacheService(lookup_result=(cached, CacheStatus.EXACT_HIT))
    routing = _FakeRoutingService(complete_result=_response("should not be used"))
    cost_service = _FakeCostService()
    gateway = _gateway(cache_service, routing, cost_service)

    result = await gateway.handle_chat_completion(_request(), trace_id="trace-1")

    assert result.message.content == "cached answer"
    assert result.cache_status == CacheStatus.EXACT_HIT
    assert result.trace_id == "trace-1"
    assert result.cost_usd == 0.0  # zeroed — no new spend was incurred
    assert routing.complete_calls == 0
    assert cost_service.calls == []


async def test_cache_miss_calls_routing_cost_service_and_backfills() -> None:
    cache_service = _FakeCacheService(lookup_result=(None, CacheStatus.MISS))
    routing = _FakeRoutingService(complete_result=_response("fresh answer"))
    cost_service = _FakeCostService(cost_usd=0.05)
    gateway = _gateway(cache_service, routing, cost_service)

    result = await gateway.handle_chat_completion(_request(), trace_id="trace-2")

    assert result.message.content == "fresh answer"
    assert result.cache_status == CacheStatus.MISS
    assert result.cost_usd == 0.05
    assert routing.complete_calls == 1
    assert len(cost_service.calls) == 1

    await asyncio.sleep(0.02)  # let the fire-and-forget backfill task run
    assert len(cache_service.backfill_calls) == 1
    _, backfilled_response, _ = cache_service.backfill_calls[0]
    assert backfilled_response.cost_usd == 0.05  # backfilled entry carries the real cost


async def test_bypass_skips_coalescing_and_backfill() -> None:
    cache_service = _FakeCacheService(lookup_result=(None, CacheStatus.BYPASSED))
    routing = _FakeRoutingService(complete_result=_response("bypassed answer"))
    gateway = _gateway(cache_service, routing)

    result = await gateway.handle_chat_completion(_request(cache_bypass=True), trace_id="trace-3")

    assert result.cache_status == CacheStatus.BYPASSED
    await asyncio.sleep(0.02)
    assert len(cache_service.backfill_calls) == 0


async def test_losing_coalescing_race_returns_winners_result_without_calling_provider() -> None:
    cache_service = _FakeCacheService(lookup_result=(None, CacheStatus.MISS))
    cache_service.lock_acquired = False
    winner_response = _response("winner already produced this", cost_usd=0.10)

    async def _wait_for_coalesced_result(request, *, tenant_id):
        return winner_response

    cache_service.wait_for_coalesced_result = _wait_for_coalesced_result
    routing = _FakeRoutingService(complete_result=_response("should not be called"))
    cost_service = _FakeCostService()
    gateway = _gateway(cache_service, routing, cost_service)

    result = await gateway.handle_chat_completion(_request(), trace_id="trace-4")

    assert result.message.content == "winner already produced this"
    assert result.cache_status == CacheStatus.EXACT_HIT
    assert result.cost_usd == 0.0  # zeroed, even though the winner's original cost was 0.10
    assert routing.complete_calls == 0
    assert cost_service.calls == []


async def test_stream_cache_hit_yields_single_chunk_then_zero_cost_metadata() -> None:
    cached = _response("full cached text", cost_usd=1.23)
    cache_service = _FakeCacheService(lookup_result=(cached, CacheStatus.EXACT_HIT))
    routing = _FakeRoutingService()
    gateway = _gateway(cache_service, routing)

    items = [
        item async for item in gateway.handle_chat_completion_stream(_request(), trace_id="trace-5")
    ]

    assert items[0] == "full cached text"
    assert isinstance(items[1], StreamMetadata)
    assert items[1].response.cost_usd == 0.0
    assert routing.stream_calls == 0


async def test_stream_cache_miss_accumulates_chunks_computes_cost_and_backfills() -> None:
    cache_service = _FakeCacheService(lookup_result=(None, CacheStatus.MISS))
    routing = _FakeRoutingService(stream_chunks=["Hel", "lo"])
    cost_service = _FakeCostService(cost_usd=0.07)
    gateway = _gateway(cache_service, routing, cost_service)

    items = [
        item async for item in gateway.handle_chat_completion_stream(_request(), trace_id="trace-6")
    ]

    text_chunks = [item for item in items if isinstance(item, str)]
    metadata_items = [item for item in items if isinstance(item, StreamMetadata)]
    assert text_chunks == ["Hel", "lo"]
    assert len(metadata_items) == 1
    assert metadata_items[0].response.cost_usd == 0.07
    assert metadata_items[0].response.usage.input_tokens == 3
    assert metadata_items[0].response.usage.output_tokens == 5

    await asyncio.sleep(0.02)  # let the fire-and-forget backfill task run
    assert len(cache_service.backfill_calls) == 1
    _, backfilled_response, _ = cache_service.backfill_calls[0]
    assert backfilled_response.message.content == "Hello"
    assert backfilled_response.provider == "openai"
    assert backfilled_response.cost_usd == 0.07


async def test_stream_bypass_skips_backfill_and_metadata_event() -> None:
    cache_service = _FakeCacheService(lookup_result=(None, CacheStatus.BYPASSED))
    routing = _FakeRoutingService(stream_chunks=["a", "b"])
    gateway = _gateway(cache_service, routing)

    items = [
        item
        async for item in gateway.handle_chat_completion_stream(
            _request(cache_bypass=True), trace_id="trace-7"
        )
    ]
    assert items == ["a", "b"]  # no trailing StreamMetadata on the bypass path
    await asyncio.sleep(0.02)
    assert len(cache_service.backfill_calls) == 0
