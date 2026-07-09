"""TraceExporter implementation that bridges our own `TraceSpan` dataclasses
onto real OpenTelemetry spans, with explicit historical start/end times (the
spans it's given already finished — sometimes seconds ago — by the time
`export()` runs in the fire-and-forget flush path) and parent-child
relationships preserved via `TraceSpan.parent_span_id`.

Actual delivery to a collector/backend is handled entirely by the SDK's
configured `BatchSpanProcessor`/`OTLPSpanExporter` (see otel_setup.py) — this
class's only job is constructing correctly-shaped OTel spans from our
domain objects.
"""

from opentelemetry import trace
from opentelemetry.trace import Span

from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.domain.interfaces.trace_exporter import TraceExporter
from llmops_gateway.observability.otel_setup import get_tracer

_ATTRIBUTE_TYPES = (str, bool, int, float)


class OtelTraceExporter(TraceExporter):
    def __init__(self, tracer_name: str = "llmops_gateway", tracer=None) -> None:
        # `tracer` is injectable so tests can pass one bound to a throwaway
        # TracerProvider (e.g. with InMemorySpanExporter) instead of fighting
        # the process-wide global tracer provider singleton.
        self._tracer = tracer or get_tracer(tracer_name)

    async def export(self, spans: list[TraceSpan]) -> None:
        # Our spans arrive in creation order, so a parent always appears
        # before any child that references it — one pass is enough to
        # resolve every parent_span_id to its already-created OTel context.
        contexts: dict[str, object] = {}
        for span in spans:
            parent_context = contexts.get(span.parent_span_id) if span.parent_span_id else None
            otel_span = self._start_span(span, parent_context)
            contexts[span.span_id] = trace.set_span_in_context(otel_span)

    def _start_span(self, span: TraceSpan, parent_context) -> Span:
        start_time_ns = _to_epoch_nanos(span.started_at)
        otel_span = self._tracer.start_span(
            span.span_name, context=parent_context, start_time=start_time_ns
        )
        otel_span.set_attribute("llmops.trace_id", span.trace_id)
        for key, value in span.metadata.items():
            attr_value = value if isinstance(value, _ATTRIBUTE_TYPES) else str(value)
            otel_span.set_attribute(key, attr_value)

        end_time_ns = _to_epoch_nanos(span.ended_at) if span.ended_at else start_time_ns
        otel_span.end(end_time=end_time_ns)
        return otel_span


def _to_epoch_nanos(moment) -> int:
    return int(moment.timestamp() * 1_000_000_000)
