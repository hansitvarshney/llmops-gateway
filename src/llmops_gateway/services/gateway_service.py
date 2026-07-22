"""Main request orchestrator — implements the flow in the architecture plan
(section 1.2, "Request lifecycle"):

  1. CacheService.lookup() — Layer 1 (Redis) then Layer 2 (Qdrant).
  2. On cache hit: stamp trace_id/latency, zero cost_usd (no new spend was
     incurred), and return immediately — the upstream provider is never
     touched.
  3. On cache miss: request-coalescing (non-streaming only, see
     CacheService) then RoutingService.complete()/stream() against the
     upstream provider fallback chain.
  4. CostService.calculate_cost_usd() once usage is known.
  5. Fire-and-forget cache write-back (`CacheService.backfill`) and trace
     persistence/export (`TracingService.flush`) — neither ever adds
     latency to the response already handed back to the client.

Every step is wrapped in a TracingService span so a single trace shows the
latency breakdown (cache_lookup / upstream_call / cost_calculation) end to
end, exactly matching the "step-by-step latency" requirement from the
architecture plan's Observability pillar.

Known limitation (documented rather than silently ignored): if a streaming
client disconnects mid-response, the generator is torn down via
`GeneratorExit` before `_finalize()` runs, so that request is not currently
traced/persisted. Handling that correctly needs the partial-completion
bookkeeping described in the plan's "stream serialization errors / client
disconnect" mitigation — left as a follow-up rather than a risky
half-implementation of async-generator cleanup semantics.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatMessage, ChatResponse, TokenUsage
from llmops_gateway.domain.interfaces.llm_provider import LLMProvider
from llmops_gateway.domain.interfaces.trace_exporter import TraceExporter
from llmops_gateway.domain.value_objects.cache_status import CacheStatus
from llmops_gateway.domain.value_objects.model_identifier import ModelIdentifier
from llmops_gateway.observability import metrics
from llmops_gateway.persistence.database import Database
from llmops_gateway.services.background_job_service import BackgroundJobService
from llmops_gateway.services.cache_service import CacheService
from llmops_gateway.services.cost_service import CostService
from llmops_gateway.services.routing_service import RoutingService
from llmops_gateway.services.trace_persistence_service import TracePersistenceService
from llmops_gateway.services.tracing_service import TracingService
from llmops_gateway.workers.payloads import build_trace_job_payload

logger = structlog.get_logger(__name__)

# Matches the row seeded by migrations/versions/0002_seed_defaults.py.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(slots=True)
class StreamMetadata:
    """Yielded as the final item from `handle_chat_completion_stream`, after
    every text delta, carrying the same usage/cost/cache-status metadata a
    non-streaming response returns inline. Kept distinct from plain `str`
    chunks so `api/v1/chat.py` can format it as its own SSE event instead of
    concatenating it into the visible completion text."""

    response: ChatResponse


class _StreamSelection:
    """Mutable box populated by RoutingService.stream()'s callback so the
    provider that actually served the stream can be identified afterward for
    accurate token counting and cost attribution."""

    def __init__(self) -> None:
        self.provider: LLMProvider | None = None
        self.request: ChatRequest | None = None

    def capture(self, provider: LLMProvider, attempt_request: ChatRequest) -> None:
        self.provider = provider
        self.request = attempt_request


class GatewayService:
    def __init__(
        self,
        cache_service: CacheService,
        routing_service: RoutingService,
        cost_service: CostService,
        database: Database | None = None,
        trace_exporters: list[TraceExporter] | None = None,
        background_jobs: BackgroundJobService | None = None,
    ) -> None:
        self._cache_service = cache_service
        self._routing_service = routing_service
        self._cost_service = cost_service
        self._database = database
        self._trace_exporters = trace_exporters or []
        self._background_jobs = background_jobs

    async def handle_chat_completion(
        self,
        request: ChatRequest,
        *,
        trace_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        api_key_id: str | None = None,
    ) -> ChatResponse:
        started_at = time.monotonic()
        tracing = TracingService(trace_id, self._database, self._trace_exporters)
        request = await self._apply_adapter_route(request, tenant_id=tenant_id)

        with tracing.span("cache_lookup") as lookup_span:
            cached, cache_status = await self._cache_service.lookup(request, tenant_id=tenant_id)
        lookup_span.metadata["cache_status"] = cache_status.value
        if request.adapter_id:
            lookup_span.metadata["adapter_id"] = request.adapter_id

        if cached is not None:
            result = self._stamp(cached, trace_id, cache_status, started_at, request=request)
            self._finalize(
                request,
                result,
                tenant_id,
                tracing,
                route="chat_completions",
                api_key_id=api_key_id,
            )
            return result

        won_lock = False
        if cache_status is not CacheStatus.BYPASSED:
            won_lock = await self._cache_service.acquire_coalescing_lock(
                request, tenant_id=tenant_id
            )
            if not won_lock:
                coalesced = await self._cache_service.wait_for_coalesced_result(
                    request, tenant_id=tenant_id
                )
                if coalesced is not None:
                    result = self._stamp(
                        coalesced, trace_id, CacheStatus.EXACT_HIT, started_at, request=request
                    )
                    self._finalize(
                        request,
                        result,
                        tenant_id,
                        tracing,
                        route="chat_completions",
                        api_key_id=api_key_id,
                    )
                    return result
                # The in-flight winner didn't finish within our wait budget —
                # fall through and call the provider ourselves rather than
                # blocking indefinitely on someone else's request.

        try:
            with tracing.span("upstream_call") as call_span:
                response = await self._routing_service.complete(request)
                call_span.metadata["provider"] = response.provider
                call_span.metadata["model"] = response.model
        finally:
            if won_lock:
                await self._cache_service.release_coalescing_lock(request, tenant_id=tenant_id)

        with tracing.span("cost_calculation") as cost_span:
            cost_usd = await self._cost_service.calculate_cost_usd(
                ModelIdentifier(provider=response.provider, model=response.model), response.usage
            )
            cost_span.metadata["cost_usd"] = cost_usd
        response = response.model_copy(update={"cost_usd": cost_usd})

        if cache_status is not CacheStatus.BYPASSED:
            asyncio.create_task(self._schedule_backfill(request, response, tenant_id))  # noqa: RUF006

        result = self._stamp(response, trace_id, cache_status, started_at, request=request)
        self._finalize(
            request,
            result,
            tenant_id,
            tracing,
            route="chat_completions",
            api_key_id=api_key_id,
        )
        return result

    async def handle_chat_completion_stream(
        self,
        request: ChatRequest,
        *,
        trace_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        api_key_id: str | None = None,
    ) -> AsyncIterator[str | StreamMetadata]:
        started_at = time.monotonic()
        tracing = TracingService(trace_id, self._database, self._trace_exporters)
        request = await self._apply_adapter_route(request, tenant_id=tenant_id)

        with tracing.span("cache_lookup") as lookup_span:
            cached, cache_status = await self._cache_service.lookup(request, tenant_id=tenant_id)
        lookup_span.metadata["cache_status"] = cache_status.value
        if request.adapter_id:
            lookup_span.metadata["adapter_id"] = request.adapter_id

        if cached is not None:
            # Fast path: the full response is already known, so there's no
            # benefit to trickling it out token-by-token — one chunk still
            # satisfies clients consuming this as an SSE/streaming endpoint.
            yield cached.message.content
            result = self._stamp(cached, trace_id, cache_status, started_at, request=request)
            yield StreamMetadata(response=result)
            self._finalize(
                request,
                result,
                tenant_id,
                tracing,
                route="chat_completions_stream",
                api_key_id=api_key_id,
            )
            return

        # Streaming responses are not request-coalesced: a second caller
        # can't safely "join" a stream that's already partway delivered to
        # someone else without a pub/sub fan-out layer, which is out of
        # scope for this phase. Concurrent identical streaming requests will
        # each call the provider directly.
        selection = _StreamSelection()
        chunks: list[str] = []
        with tracing.span("upstream_call") as call_span:
            stream = self._routing_service.stream(request, on_provider_selected=selection.capture)
            async for chunk in stream:
                chunks.append(chunk)
                yield chunk
            call_span.metadata["provider"] = (
                selection.provider.name if selection.provider else "unknown"
            )

        if cache_status is CacheStatus.BYPASSED:
            return

        full_text = "".join(chunks)
        provider = selection.provider
        attempt_request = selection.request or request
        if provider is not None:
            usage = await provider.count_tokens(attempt_request, full_text)
            provider_name = provider.name
        else:
            # Every chunk came from cache/nowhere (e.g. an empty response) —
            # keep this defensive branch so a malformed stream never raises.
            usage = TokenUsage(input_tokens=0, output_tokens=0)
            provider_name = "unknown"

        with tracing.span("cost_calculation") as cost_span:
            cost_usd = await self._cost_service.calculate_cost_usd(
                ModelIdentifier(provider=provider_name, model=request.model), usage
            )
            cost_span.metadata["cost_usd"] = cost_usd

        response = ChatResponse(
            id=str(uuid.uuid4()),
            model=request.model,
            provider=provider_name,
            message=ChatMessage(role="assistant", content=full_text),
            usage=usage,
            cost_usd=cost_usd,
            cache_status=cache_status,
            trace_id=trace_id,
            created_at=datetime.now(UTC),
            latency_ms=(time.monotonic() - started_at) * 1000,
            adapter_id=request.adapter_id,
            model_alias=request.model_alias,
            adapter_stage=request.adapter_stage,
        )
        asyncio.create_task(  # noqa: RUF006 - deliberately fire-and-forget
            self._schedule_backfill(request, response, tenant_id)
        )
        yield StreamMetadata(response=response)
        self._finalize(
            request,
            response,
            tenant_id,
            tracing,
            route="chat_completions_stream",
            api_key_id=api_key_id,
        )

    def _finalize(
        self,
        request: ChatRequest,
        response: ChatResponse,
        tenant_id: str,
        tracing: TracingService,
        *,
        route: str,
        api_key_id: str | None = None,
    ) -> None:
        """Records in-process metrics synchronously (cheap, no I/O) and
        fires off trace persistence/export as a background task — neither
        should ever add latency to the response already returned to the
        client. Only reached on a successful completion; provider/routing
        exceptions propagate past this and are not yet traced (see the
        module docstring's "known limitation")."""
        metrics.record_request_metrics(
            route=route,
            tenant_id=tenant_id,
            provider=response.provider,
            model=response.model,
            cache_status=response.cache_status.value,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
        )
        if self._background_jobs is None:
            asyncio.create_task(  # noqa: RUF006
                tracing.flush(
                    request=request,
                    response=response,
                    tenant_id=tenant_id,
                    http_status=200,
                    api_key_id=api_key_id,
                )
            )
            return

        payload = build_trace_job_payload(
            trace_id=tracing._trace_id,
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            http_status=200,
            request=request,
            response=response,
            spans=tracing.spans,
        )

        async def persist() -> None:
            if self._database is None:
                return
            await TracePersistenceService.persist(
                self._database,
                trace_id=tracing._trace_id,
                tenant_id=tenant_id,
                api_key_id=api_key_id,
                http_status=200,
                request=request,
                response=response,
                spans=tracing.spans,
            )

        async def export() -> None:
            for exporter in self._trace_exporters:
                try:
                    await exporter.export(tracing.spans)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "trace_export_failed",
                        trace_id=tracing._trace_id,
                        exporter=type(exporter).__name__,
                        error=str(exc),
                    )

        asyncio.create_task(  # noqa: RUF006
            self._background_jobs.run_trace_flush(
                persist_coro=persist,
                export_coro=export,
                persist_payload=payload,
                export_payload=payload,
            )
        )

    async def _schedule_backfill(
        self,
        request: ChatRequest,
        response: ChatResponse,
        tenant_id: str,
    ) -> None:
        async def backfill() -> None:
            await self._cache_service.backfill(request, response, tenant_id=tenant_id)

        if self._background_jobs is None:
            await backfill()
            return

        await self._background_jobs.run_backfill(
            backfill_coro=backfill,
            request_payload=request.model_dump(mode="json"),
            response_payload=response.model_dump(mode="json"),
            tenant_id=tenant_id,
        )

    async def _apply_adapter_route(self, request: ChatRequest, *, tenant_id: str) -> ChatRequest:
        """Remap model alias → base_model + adapter_id before cache/routing."""
        if request.adapter_id and request.model_alias:
            return request
        if self._database is None:
            return request
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            return request

        stage = request.adapter_stage  # None → canary-aware resolve
        from llmops_gateway.persistence.repositories.adapter_route_repository import (
            AdapterRouteRepository,
        )

        routing_key = f"{tenant_id}:{request.model}:{request.canonical_prompt()}"
        try:
            async with self._database.session() as session:
                row = await AdapterRouteRepository(session).resolve_with_canary(
                    tenant_id=tenant_uuid,
                    model_alias=request.model,
                    routing_key=routing_key,
                    preferred_stage=stage,
                )
        except Exception as exc:  # noqa: BLE001 — routing must not fail closed on DB blips
            logger.warning("adapter_route_lookup_failed", error=str(exc), tenant_id=tenant_id)
            return request

        if row is None:
            return request
        return request.model_copy(
            update={
                "model_alias": request.model,
                "model": row.base_model,
                "adapter_id": row.adapter_id,
                "adapter_stage": row.stage,
            }
        )

    @staticmethod
    def _stamp(
        response: ChatResponse,
        trace_id: str,
        cache_status: CacheStatus,
        started_at: float,
        *,
        request: ChatRequest | None = None,
    ) -> ChatResponse:
        cost_usd = (
            0.0
            if cache_status in (CacheStatus.EXACT_HIT, CacheStatus.SEMANTIC_HIT)
            else response.cost_usd
        )
        update: dict = {
            "trace_id": trace_id,
            "cache_status": cache_status,
            "latency_ms": (time.monotonic() - started_at) * 1000,
            "cost_usd": cost_usd,
        }
        if request is not None:
            update["adapter_id"] = request.adapter_id
            update["model_alias"] = request.model_alias
            update["adapter_stage"] = request.adapter_stage
        return response.model_copy(update=update)
