"""TracePersistenceService idempotency tests."""

import uuid
from datetime import UTC, datetime

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatMessage as RespMessage
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.domain.value_objects.cache_status import CacheStatus
from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.persistence.repositories.request_repository import RequestRepository
from llmops_gateway.services.trace_persistence_service import TracePersistenceService


async def _seed_tenant(sqlite_database) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with sqlite_database.session() as session:
        session.add(
            TenantModel(id=tenant_id, name="Tenant", slug=f"tenant-{tenant_id.hex[:8]}")
        )
    return tenant_id


async def test_persist_is_idempotent_by_trace_id(sqlite_database) -> None:
    tenant_id = await _seed_tenant(sqlite_database)
    request = ChatRequest(model="gpt-4o", messages=[ChatMessage(role="user", content="hi")])
    response = ChatResponse(
        id="resp-1",
        model="gpt-4o",
        provider="openai",
        message=RespMessage(role="assistant", content="hello"),
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.01,
        cache_status=CacheStatus.MISS,
        trace_id="trace-idem",
        created_at=datetime.now(UTC),
        latency_ms=10.0,
    )
    spans = [
        TraceSpan(
            trace_id="trace-idem",
            span_id="trace-idem:cache_lookup:0",
            span_name="cache_lookup",
            started_at=datetime.now(UTC),
        )
    ]

    await TracePersistenceService.persist(
        sqlite_database,
        trace_id="trace-idem",
        tenant_id=str(tenant_id),
        api_key_id=None,
        http_status=200,
        request=request,
        response=response,
        spans=spans,
    )
    await TracePersistenceService.persist(
        sqlite_database,
        trace_id="trace-idem",
        tenant_id=str(tenant_id),
        api_key_id=None,
        http_status=200,
        request=request,
        response=response,
        spans=spans,
    )

    async with sqlite_database.session() as session:
        record = await RequestRepository(session).get_by_trace_id("trace-idem")

    assert record is not None
