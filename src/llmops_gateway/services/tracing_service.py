"""Builds TraceSpan records for a request and hands them off for async
persistence + export once the request is complete.

Spans are accumulated in-memory for the lifetime of a single request
(cache_lookup, upstream_call, cost_calculation, ...) and flushed as one
batch via `flush()` — always from a fire-and-forget task (see
GatewayService), never on the synchronous request path. `flush()` itself
must never raise: a tracing/persistence failure happens strictly after the
response has already been sent to the client, so it can only be logged,
never surfaced as a request failure.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import structlog

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.domain.interfaces.trace_exporter import TraceExporter
from llmops_gateway.persistence.database import Database
from llmops_gateway.services.trace_persistence_service import TracePersistenceService

logger = structlog.get_logger(__name__)


class TracingService:
    def __init__(
        self,
        trace_id: str,
        database: Database | None = None,
        exporters: list[TraceExporter] | None = None,
    ) -> None:
        self._trace_id = trace_id
        self._database = database
        self._exporters = exporters or []
        self.spans: list[TraceSpan] = []

    @contextmanager
    def span(self, name: str, parent_span_id: str | None = None) -> Iterator[TraceSpan]:
        span = TraceSpan(
            trace_id=self._trace_id,
            span_id=f"{self._trace_id}:{name}:{len(self.spans)}",
            span_name=name,
            parent_span_id=parent_span_id,
            started_at=datetime.now(UTC),
        )
        self.spans.append(span)
        try:
            yield span
        finally:
            span.ended_at = datetime.now(UTC)

    async def flush(
        self,
        *,
        request: ChatRequest,
        response: ChatResponse,
        tenant_id: str,
        http_status: int,
        api_key_id: str | None = None,
    ) -> None:
        try:
            await self._persist(request, response, tenant_id, http_status, api_key_id)
        except Exception as exc:  # noqa: BLE001 - persistence must never break the caller
            logger.warning("trace_persist_failed", trace_id=self._trace_id, error=str(exc))

        for exporter in self._exporters:
            try:
                await exporter.export(self.spans)
            except Exception as exc:  # noqa: BLE001 - export must never break the caller
                logger.warning(
                    "trace_export_failed",
                    trace_id=self._trace_id,
                    exporter=type(exporter).__name__,
                    error=str(exc),
                )

    async def _persist(
        self,
        request: ChatRequest,
        response: ChatResponse,
        tenant_id: str,
        http_status: int,
        api_key_id: str | None,
    ) -> None:
        if self._database is None:
            return

        await TracePersistenceService.persist(
            self._database,
            trace_id=self._trace_id,
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            http_status=http_status,
            request=request,
            response=response,
            spans=self.spans,
        )
