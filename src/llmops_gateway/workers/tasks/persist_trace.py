"""Background job: persist a request + its spans + token usage to Postgres.

Idempotent (skips if trace_id already exists) so arq's at-least-once retry
semantics never produce duplicate rows.
"""

from typing import Any

import structlog

from llmops_gateway.services.trace_persistence_service import TracePersistenceService
from llmops_gateway.workers.payloads import parse_trace_job_payload

logger = structlog.get_logger(__name__)


async def persist_trace(ctx: dict[str, Any], trace_payload: dict[str, Any]) -> None:
    database = ctx["db"]
    trace_id, tenant_id, api_key_id, http_status, request, response, spans = (
        parse_trace_job_payload(trace_payload)
    )
    try:
        await TracePersistenceService.persist(
            database,
            trace_id=trace_id,
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            http_status=http_status,
            request=request,
            response=response,
            spans=spans,
        )
    except Exception as exc:
        logger.warning("worker_persist_trace_failed", trace_id=trace_id, error=str(exc))
        raise
