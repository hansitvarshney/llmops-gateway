"""OpenTelemetry tracer provider bootstrap.

Configures a batched OTLP exporter (never a synchronous per-span exporter —
`BatchSpanProcessor` exports off a background thread and swallows/retries
connection failures internally, so this is safe to call even when no
collector is listening, e.g. in local dev without `docker compose up`)
pointed at `settings.otel_exporter_otlp_endpoint`, which can fan out to
Jaeger/Datadog/Langfuse via an OTel Collector pipeline — see
infra/docker/otel-collector-config.yaml.
"""

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from llmops_gateway.config.settings import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

_tracer_provider: TracerProvider | None = None


def configure_otel(settings: Settings) -> TracerProvider | None:
    """Idempotent: safe to call once at startup. Returns None (and leaves
    the global no-op tracer provider in place) when tracing is disabled."""
    global _tracer_provider
    if not settings.tracing_enabled:
        return None

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _tracer_provider = provider
    return provider


def instrument_fastapi(app: "FastAPI") -> None:
    """Auto-instruments inbound HTTP request spans (method, route, status).
    This is separate from our own TraceSpan/TracingService pipeline — that
    one captures gateway-specific spans (cache_lookup, upstream_call, ...)
    that FastAPI's own instrumentation has no visibility into."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str = "llmops_gateway"):
    return trace.get_tracer(name)


def shutdown_otel() -> None:
    """Flushes any buffered spans before the process exits — otherwise the
    last batch sitting in BatchSpanProcessor's queue is silently dropped."""
    global _tracer_provider
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None
