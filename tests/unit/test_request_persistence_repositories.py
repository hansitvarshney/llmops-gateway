"""RequestRepository + SpanRepository + TokenUsageRepository against a real
in-memory SQLite database — verifies the full "one request, its spans, its
token usage" write path (including the FK relationships between them) the
way TracingService._persist() actually uses them together."""

import uuid
from datetime import UTC, datetime, timedelta

from llmops_gateway.domain.entities.chat_response import TokenUsage
from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.persistence.repositories.request_repository import RequestRepository
from llmops_gateway.persistence.repositories.span_repository import SpanRepository
from llmops_gateway.persistence.repositories.token_usage_repository import TokenUsageRepository


async def _seed_tenant(sqlite_database) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with sqlite_database.session() as session:
        session.add(TenantModel(id=tenant_id, name="Test Tenant", slug=f"test-{tenant_id.hex[:8]}"))
    return tenant_id


async def test_create_request_populates_id_before_commit(sqlite_database) -> None:
    tenant_id = await _seed_tenant(sqlite_database)

    async with sqlite_database.session() as session:
        repo = RequestRepository(session)
        record = await repo.create(
            trace_id="trace-1",
            tenant_id=tenant_id,
            provider="openai",
            model_requested="gpt-4o",
            model_used="gpt-4o",
            status="ok",
            cache_status="MISS",
            http_status=200,
            is_stream=False,
            total_latency_ms=123.4,
            completed_at=datetime.now(UTC),
        )
        assert record.id is not None  # flush() assigned it pre-commit


async def test_get_by_trace_id_round_trips(sqlite_database) -> None:
    tenant_id = await _seed_tenant(sqlite_database)

    async with sqlite_database.session() as session:
        repo = RequestRepository(session)
        await repo.create(
            trace_id="trace-lookup",
            tenant_id=tenant_id,
            provider="anthropic",
            model_requested="claude-3-5-sonnet-20241022",
            status="ok",
            http_status=200,
            is_stream=True,
        )

    async with sqlite_database.session() as session:
        repo = RequestRepository(session)
        found = await repo.get_by_trace_id("trace-lookup")
        missing = await repo.get_by_trace_id("does-not-exist")

    assert found is not None
    assert found.provider == "anthropic"
    assert found.is_stream is True
    assert missing is None


async def test_span_repository_bulk_create_persists_all_spans(sqlite_database) -> None:
    tenant_id = await _seed_tenant(sqlite_database)
    now = datetime.now(UTC)

    async with sqlite_database.session() as session:
        request_record = await RequestRepository(session).create(
            trace_id="trace-spans",
            tenant_id=tenant_id,
            provider="openai",
            model_requested="gpt-4o",
            status="ok",
            http_status=200,
            is_stream=False,
        )
        spans = [
            TraceSpan(
                trace_id="trace-spans",
                span_id="trace-spans:cache_lookup:0",
                span_name="cache_lookup",
                started_at=now,
                ended_at=now + timedelta(milliseconds=5),
                metadata={"cache_status": "MISS"},
            ),
            TraceSpan(
                trace_id="trace-spans",
                span_id="trace-spans:upstream_call:1",
                span_name="upstream_call",
                started_at=now + timedelta(milliseconds=5),
                ended_at=now + timedelta(milliseconds=200),
                metadata={"provider": "openai"},
            ),
        ]
        await SpanRepository(session).bulk_create(request_record.id, spans)

    async with sqlite_database.session() as session:
        from sqlalchemy import select

        from llmops_gateway.persistence.models.trace_span import RequestSpanModel

        result = await session.execute(
            select(RequestSpanModel).where(RequestSpanModel.request_id == request_record.id)
        )
        persisted = result.scalars().all()

    assert len(persisted) == 2
    names = {span.span_name for span in persisted}
    assert names == {"cache_lookup", "upstream_call"}
    upstream = next(s for s in persisted if s.span_name == "upstream_call")
    assert upstream.span_metadata == {"provider": "openai"}


async def test_span_repository_bulk_create_noop_on_empty_list(sqlite_database) -> None:
    tenant_id = await _seed_tenant(sqlite_database)
    async with sqlite_database.session() as session:
        request_record = await RequestRepository(session).create(
            trace_id="trace-empty",
            tenant_id=tenant_id,
            provider="openai",
            model_requested="gpt-4o",
            status="ok",
            http_status=200,
            is_stream=False,
        )
        await SpanRepository(session).bulk_create(request_record.id, [])  # must not raise


async def test_token_usage_repository_create(sqlite_database) -> None:
    tenant_id = await _seed_tenant(sqlite_database)

    async with sqlite_database.session() as session:
        request_record = await RequestRepository(session).create(
            trace_id="trace-usage",
            tenant_id=tenant_id,
            provider="openai",
            model_requested="gpt-4o",
            status="ok",
            http_status=200,
            is_stream=False,
        )
        usage_record = await TokenUsageRepository(session).create(
            request_id=request_record.id,
            usage=TokenUsage(input_tokens=120, output_tokens=45),
            cost_usd=0.00345,
        )

    assert usage_record.input_tokens == 120
    assert usage_record.output_tokens == 45
    assert usage_record.total_tokens == 165
    assert float(usage_record.cost_usd) == 0.00345
