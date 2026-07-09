"""Shared trace persistence logic used by TracingService and arq workers."""

import uuid

import structlog

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.persistence.database import Database
from llmops_gateway.persistence.repositories.request_repository import RequestRepository
from llmops_gateway.persistence.repositories.span_repository import SpanRepository
from llmops_gateway.persistence.repositories.token_usage_repository import TokenUsageRepository

logger = structlog.get_logger(__name__)


class TracePersistenceService:
    @staticmethod
    async def persist(
        database: Database,
        *,
        trace_id: str,
        tenant_id: str,
        api_key_id: str | None,
        http_status: int,
        request: ChatRequest,
        response: ChatResponse,
        spans: list[TraceSpan],
    ) -> None:
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            logger.debug("trace_persist_skipped_non_uuid_tenant", tenant_id=tenant_id)
            return

        async with database.session() as session:
            request_repo = RequestRepository(session)
            existing = await request_repo.get_by_trace_id(trace_id)
            if existing is not None:
                logger.debug("trace_persist_idempotent_skip", trace_id=trace_id)
                return

            record = await request_repo.create(
                trace_id=trace_id,
                tenant_id=tenant_uuid,
                api_key_id=uuid.UUID(api_key_id) if api_key_id else None,
                provider=response.provider,
                model_requested=request.model,
                model_used=response.model,
                status="ok" if http_status < 400 else "error",
                cache_status=response.cache_status.value,
                http_status=http_status,
                is_stream=request.stream,
                total_latency_ms=response.latency_ms,
                completed_at=response.created_at,
            )
            await SpanRepository(session).bulk_create(record.id, spans)
            await TokenUsageRepository(session).create(
                request_id=record.id,
                usage=response.usage,
                cost_usd=response.cost_usd,
            )
