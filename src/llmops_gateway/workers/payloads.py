"""Serialize/deserialize trace and cache job payloads for arq workers."""

from datetime import datetime
from typing import Any

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.domain.entities.trace_span import TraceSpan


def spans_to_payload(spans: list[TraceSpan]) -> list[dict[str, Any]]:
    return [
        {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "span_name": span.span_name,
            "parent_span_id": span.parent_span_id,
            "started_at": span.started_at.isoformat(),
            "ended_at": span.ended_at.isoformat() if span.ended_at else None,
            "metadata": span.metadata,
        }
        for span in spans
    ]


def spans_from_payload(payload: list[dict[str, Any]]) -> list[TraceSpan]:
    spans: list[TraceSpan] = []
    for item in payload:
        span = TraceSpan(
            trace_id=item["trace_id"],
            span_id=item["span_id"],
            span_name=item["span_name"],
            parent_span_id=item.get("parent_span_id"),
            started_at=datetime.fromisoformat(item["started_at"]),
            metadata=item.get("metadata", {}),
        )
        if item.get("ended_at"):
            span.ended_at = datetime.fromisoformat(item["ended_at"])
        spans.append(span)
    return spans


def build_trace_job_payload(
    *,
    trace_id: str,
    tenant_id: str,
    api_key_id: str | None,
    http_status: int,
    request: ChatRequest,
    response: ChatResponse,
    spans: list[TraceSpan],
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "api_key_id": api_key_id,
        "http_status": http_status,
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
        "spans": spans_to_payload(spans),
    }


def parse_trace_job_payload(payload: dict[str, Any]) -> tuple[
    str,
    str,
    str | None,
    int,
    ChatRequest,
    ChatResponse,
    list[TraceSpan],
]:
    return (
        payload["trace_id"],
        payload["tenant_id"],
        payload.get("api_key_id"),
        payload["http_status"],
        ChatRequest.model_validate(payload["request"]),
        ChatResponse.model_validate(payload["response"]),
        spans_from_payload(payload["spans"]),
    )
