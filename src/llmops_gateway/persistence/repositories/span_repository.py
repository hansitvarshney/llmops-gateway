"""Data-access layer for `request_spans`."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.persistence.models.trace_span import RequestSpanModel


class SpanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, request_id: uuid.UUID, spans: list[TraceSpan]) -> None:
        """Batches every span for a request into one INSERT round-trip
        rather than one write per span, per the "Postgres write
        amplification" mitigation in the architecture plan."""
        if not spans:
            return
        models = [
            RequestSpanModel(
                request_id=request_id,
                span_name=span.span_name,
                parent_span_id=span.parent_span_id,
                started_at=span.started_at,
                ended_at=span.ended_at,
                duration_ms=span.duration_ms,
                span_metadata=span.metadata,
            )
            for span in spans
        ]
        self._session.add_all(models)
        await self._session.flush()
