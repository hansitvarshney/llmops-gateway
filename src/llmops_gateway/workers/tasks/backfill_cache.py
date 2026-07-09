"""Background job: write a fresh upstream response into both cache layers."""

from typing import Any

import structlog

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse

logger = structlog.get_logger(__name__)


async def backfill_cache(
    ctx: dict[str, Any],
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    tenant_id: str,
) -> None:
    cache_service = ctx["cache_service"]
    request = ChatRequest.model_validate(request_payload)
    response = ChatResponse.model_validate(response_payload)
    try:
        await cache_service.backfill(request, response, tenant_id=tenant_id)
    except Exception as exc:
        logger.warning("worker_backfill_cache_failed", tenant_id=tenant_id, error=str(exc))
        raise
