"""Factory for TraceExporter instances based on settings."""

from llmops_gateway.config.settings import Settings
from llmops_gateway.domain.interfaces.trace_exporter import TraceExporter
from llmops_gateway.observability.langfuse_exporter import LangfuseExporter
from llmops_gateway.observability.otel_trace_exporter import OtelTraceExporter


def build_trace_exporters(settings: Settings) -> list[TraceExporter]:
    exporters: list[TraceExporter] = []
    if settings.tracing_enabled:
        exporters.append(OtelTraceExporter(tracer_name=settings.otel_service_name))
    if settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key:
        exporters.append(
            LangfuseExporter(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        )
    return exporters
