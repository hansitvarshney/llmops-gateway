"""Background job: export a batch of spans to configured TraceExporter(s)."""

from typing import Any

import structlog

from llmops_gateway.workers.payloads import spans_from_payload

logger = structlog.get_logger(__name__)


async def export_otel_spans(ctx: dict[str, Any], trace_payload: dict[str, Any]) -> None:
    exporters = ctx.get("trace_exporters", [])
    spans = spans_from_payload(trace_payload["spans"])
    trace_id = trace_payload.get("trace_id", "")

    for exporter in exporters:
        try:
            await exporter.export(spans)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "worker_trace_export_failed",
                trace_id=trace_id,
                exporter=type(exporter).__name__,
                error=str(exc),
            )
