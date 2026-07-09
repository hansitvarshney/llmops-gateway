"""TracingService: span capture, persistence (real SQLite database), and
export (fake TraceExporter) — plus the "must never raise" guarantees that
justify running flush() as a fire-and-forget task from GatewayService."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.value_objects.cache_status import CacheStatus
from llmops_gateway.persistence.models.request_log import RequestLogModel
from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.persistence.models.token_usage import TokenUsageModel
from llmops_gateway.persistence.models.trace_span import RequestSpanModel
from llmops_gateway.services.tracing_service import TracingService


class _FakeExporter:
    def __init__(self, should_raise: bool = False) -> None:
        self.exported_batches: list[list] = []
        self.should_raise = should_raise

    async def export(self, spans):
        if self.should_raise:
            raise RuntimeError("exporter backend unreachable")
        self.exported_batches.append(spans)


def _request() -> ChatRequest:
    return ChatRequest(model="gpt-4o", messages=[ChatMessage(role="user", content="hi")])


def _response(trace_id: str) -> ChatResponse:
    return ChatResponse(
        id="1",
        model="gpt-4o",
        provider="openai",
        message=ChatMessage(role="assistant", content="hello"),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        cost_usd=0.001,
        cache_status=CacheStatus.MISS,
        trace_id=trace_id,
        created_at=datetime.now(UTC),
        latency_ms=42.0,
    )


async def _seed_tenant(sqlite_database) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with sqlite_database.session() as session:
        session.add(TenantModel(id=tenant_id, name="Test Tenant", slug=f"test-{tenant_id.hex[:8]}"))
    return tenant_id


def test_span_context_manager_records_start_and_end() -> None:
    tracing = TracingService("trace-1")
    with tracing.span("cache_lookup") as span:
        span.metadata["cache_status"] = "MISS"

    assert len(tracing.spans) == 1
    assert tracing.spans[0].span_name == "cache_lookup"
    assert tracing.spans[0].ended_at is not None
    assert tracing.spans[0].duration_ms is not None
    assert tracing.spans[0].metadata == {"cache_status": "MISS"}


def test_nested_spans_capture_parent_child_relationship() -> None:
    tracing = TracingService("trace-1")
    with tracing.span("root") as root:
        with tracing.span("child", parent_span_id=root.span_id):
            pass

    assert tracing.spans[1].parent_span_id == tracing.spans[0].span_id


async def test_flush_without_database_is_a_safe_noop() -> None:
    tracing = TracingService("trace-1", database=None, exporters=[])
    with tracing.span("cache_lookup"):
        pass
    # Must not raise even with nothing configured to persist/export to.
    await tracing.flush(
        request=_request(), response=_response("trace-1"), tenant_id="not-a-uuid", http_status=200
    )


async def test_flush_persists_request_spans_and_token_usage(sqlite_database) -> None:
    tenant_id = await _seed_tenant(sqlite_database)
    tracing = TracingService("trace-persist", database=sqlite_database, exporters=[])
    with tracing.span("cache_lookup") as lookup_span:
        lookup_span.metadata["cache_status"] = "MISS"
    with tracing.span("upstream_call") as call_span:
        call_span.metadata["provider"] = "openai"

    response = _response("trace-persist")
    await tracing.flush(
        request=_request(),
        response=response,
        tenant_id=str(tenant_id),
        http_status=200,
    )

    async with sqlite_database.session() as session:
        request_row = (
            await session.execute(
                select(RequestLogModel).where(RequestLogModel.trace_id == "trace-persist")
            )
        ).scalar_one()
        span_rows = (
            await session.execute(
                select(RequestSpanModel).where(RequestSpanModel.request_id == request_row.id)
            )
        ).scalars().all()
        usage_row = (
            await session.execute(
                select(TokenUsageModel).where(TokenUsageModel.request_id == request_row.id)
            )
        ).scalar_one()

    assert request_row.provider == "openai"
    assert request_row.cache_status == "MISS"
    assert request_row.status == "ok"
    assert len(span_rows) == 2
    assert usage_row.input_tokens == 10
    assert usage_row.output_tokens == 5
    assert float(usage_row.cost_usd) == 0.001


async def test_flush_skips_persistence_for_non_uuid_tenant(sqlite_database) -> None:
    tracing = TracingService("trace-skip", database=sqlite_database, exporters=[])
    await tracing.flush(
        request=_request(), response=_response("trace-skip"), tenant_id="default", http_status=200
    )

    async with sqlite_database.session() as session:
        result = await session.execute(
            select(RequestLogModel).where(RequestLogModel.trace_id == "trace-skip")
        )
        assert result.scalar_one_or_none() is None


async def test_flush_swallows_persistence_errors(sqlite_database) -> None:
    tracing = TracingService("trace-bad-fk", database=sqlite_database, exporters=[])
    # A tenant_id that's a syntactically valid UUID but doesn't exist as an
    # actual tenants row violates the FK — flush() must log and swallow it.
    await tracing.flush(
        request=_request(),
        response=_response("trace-bad-fk"),
        tenant_id=str(uuid.uuid4()),
        http_status=200,
    )  # must not raise


async def test_flush_exports_to_every_configured_exporter() -> None:
    exporter_a = _FakeExporter()
    exporter_b = _FakeExporter()
    tracing = TracingService("trace-export", database=None, exporters=[exporter_a, exporter_b])
    with tracing.span("cache_lookup"):
        pass

    await tracing.flush(
        request=_request(), response=_response("trace-export"), tenant_id="default", http_status=200
    )

    assert len(exporter_a.exported_batches) == 1
    assert len(exporter_b.exported_batches) == 1
    assert exporter_a.exported_batches[0][0].span_name == "cache_lookup"


async def test_flush_swallows_export_errors_and_still_tries_remaining_exporters() -> None:
    broken = _FakeExporter(should_raise=True)
    healthy = _FakeExporter()
    tracing = TracingService("trace-export-fail", database=None, exporters=[broken, healthy])
    with tracing.span("cache_lookup"):
        pass

    await tracing.flush(
        request=_request(),
        response=_response("trace-export-fail"),
        tenant_id="default",
        http_status=200,
    )  # must not raise

    assert len(healthy.exported_batches) == 1
