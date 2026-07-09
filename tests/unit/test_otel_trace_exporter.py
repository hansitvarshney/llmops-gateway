"""OtelTraceExporter, verified against a real OTel SDK TracerProvider wired
to `InMemorySpanExporter` (no live collector needed) — checks that our
TraceSpan dataclasses turn into correctly-shaped, correctly-linked OTel
spans rather than just asserting the bridge "doesn't crash"."""

from datetime import UTC, datetime, timedelta

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.observability.otel_trace_exporter import OtelTraceExporter


def _tracer_and_exporter():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


async def test_export_creates_one_otel_span_per_trace_span() -> None:
    tracer, exporter = _tracer_and_exporter()
    otel_exporter = OtelTraceExporter(tracer=tracer)

    now = datetime.now(UTC)
    span = TraceSpan(
        trace_id="t1",
        span_id="t1:cache_lookup:0",
        span_name="cache_lookup",
        started_at=now,
        ended_at=now + timedelta(milliseconds=5),
        metadata={"cache_status": "MISS"},
    )

    await otel_exporter.export([span])

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].name == "cache_lookup"
    assert finished[0].attributes["llmops.trace_id"] == "t1"
    assert finished[0].attributes["cache_status"] == "MISS"


async def test_export_preserves_parent_child_relationship() -> None:
    tracer, exporter = _tracer_and_exporter()
    otel_exporter = OtelTraceExporter(tracer=tracer)

    now = datetime.now(UTC)
    root = TraceSpan(
        trace_id="t1",
        span_id="t1:root:0",
        span_name="root",
        started_at=now,
        ended_at=now + timedelta(milliseconds=100),
    )
    child = TraceSpan(
        trace_id="t1",
        span_id="t1:child:1",
        span_name="child",
        started_at=now + timedelta(milliseconds=10),
        ended_at=now + timedelta(milliseconds=50),
        parent_span_id=root.span_id,
    )

    await otel_exporter.export([root, child])

    finished = {span.name: span for span in exporter.get_finished_spans()}
    assert finished["child"].parent.span_id == finished["root"].context.span_id


async def test_export_stringifies_non_primitive_metadata_values() -> None:
    tracer, exporter = _tracer_and_exporter()
    otel_exporter = OtelTraceExporter(tracer=tracer)

    now = datetime.now(UTC)
    span = TraceSpan(
        trace_id="t1",
        span_id="t1:x:0",
        span_name="x",
        started_at=now,
        ended_at=now,
        metadata={"nested": {"a": 1}, "count": 3, "ok": True},
    )

    await otel_exporter.export([span])

    attrs = exporter.get_finished_spans()[0].attributes
    assert attrs["nested"] == "{'a': 1}"
    assert attrs["count"] == 3
    assert attrs["ok"] is True


async def test_export_handles_span_without_end_time() -> None:
    tracer, exporter = _tracer_and_exporter()
    otel_exporter = OtelTraceExporter(tracer=tracer)

    span = TraceSpan(
        trace_id="t1",
        span_id="t1:unfinished:0",
        span_name="unfinished",
        started_at=datetime.now(UTC),
    )
    await otel_exporter.export([span])  # must not raise despite ended_at being None

    assert len(exporter.get_finished_spans()) == 1
