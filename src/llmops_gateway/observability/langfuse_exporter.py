"""TraceExporter implementation that maps TraceSpan batches onto Langfuse's
public batch ingestion API (`POST {host}/api/public/ingestion`), so the same
spans GatewayService already captures can show up in Langfuse without any
gateway code needing to know Langfuse exists — see the pluggable
TraceExporter interface.

Kept intentionally minimal (a `trace-create` event plus one `span-create`
event per span) rather than depending on the full Langfuse SDK, since the
SDK is oriented around synchronous/threaded buffering that doesn't fit this
codebase's async fire-and-forget flush model. Every failure mode (network,
auth, malformed response) is caught and logged rather than raised — per the
TraceExporter contract, tracing must never be able to fail a user-facing
request retroactively.
"""

import uuid
from datetime import UTC, datetime

import httpx
import structlog

from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.domain.interfaces.trace_exporter import TraceExporter

logger = structlog.get_logger(__name__)

INGESTION_PATH = "/api/public/ingestion"
REQUEST_TIMEOUT_SECONDS = 5.0


class LangfuseExporter(TraceExporter):
    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        self._public_key = public_key
        self._secret_key = secret_key
        self._host = host.rstrip("/")

    async def export(self, spans: list[TraceSpan]) -> None:
        if not spans:
            return

        events = self._build_events(spans)
        try:
            async with httpx.AsyncClient(
                base_url=self._host,
                auth=(self._public_key, self._secret_key),
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as client:
                response = await client.post(INGESTION_PATH, json={"batch": events})
                if response.status_code >= 400:
                    logger.warning(
                        "langfuse_export_rejected",
                        status_code=response.status_code,
                        body=response.text[:500],
                    )
        except httpx.HTTPError as exc:
            logger.warning("langfuse_export_failed", error=str(exc))

    def _build_events(self, spans: list[TraceSpan]) -> list[dict]:
        trace_id = spans[0].trace_id
        now_iso = datetime.now(UTC).isoformat()

        events: list[dict] = [
            {
                "id": str(uuid.uuid4()),
                "timestamp": now_iso,
                "type": "trace-create",
                "body": {"id": trace_id, "name": "chat_completion", "timestamp": now_iso},
            }
        ]
        for span in spans:
            events.append(
                {
                    "id": str(uuid.uuid4()),
                    "timestamp": now_iso,
                    "type": "span-create",
                    "body": {
                        "id": span.span_id,
                        "traceId": span.trace_id,
                        "parentObservationId": span.parent_span_id,
                        "name": span.span_name,
                        "startTime": span.started_at.isoformat(),
                        "endTime": span.ended_at.isoformat() if span.ended_at else None,
                        "metadata": span.metadata,
                    },
                }
            )
        return events
