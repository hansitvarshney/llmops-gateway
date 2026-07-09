"""Worker payload serialization round-trip tests."""

from datetime import UTC, datetime

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatMessage as RespMessage
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.entities.trace_span import TraceSpan
from llmops_gateway.domain.value_objects.cache_status import CacheStatus
from llmops_gateway.workers.payloads import build_trace_job_payload, parse_trace_job_payload


def test_trace_payload_round_trip() -> None:
    request = ChatRequest(model="gpt-4o", messages=[ChatMessage(role="user", content="hi")])
    response = ChatResponse(
        id="r1",
        model="gpt-4o",
        provider="openai",
        message=RespMessage(role="assistant", content="ok"),
        usage=TokenUsage(input_tokens=1, output_tokens=2),
        cost_usd=0.5,
        cache_status=CacheStatus.MISS,
        trace_id="trace-1",
        created_at=datetime.now(UTC),
        latency_ms=12.3,
    )
    spans = [
        TraceSpan(
            trace_id="trace-1",
            span_id="trace-1:cache_lookup:0",
            span_name="cache_lookup",
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            metadata={"cache_status": "MISS"},
        )
    ]
    payload = build_trace_job_payload(
        trace_id="trace-1",
        tenant_id="00000000-0000-0000-0000-000000000001",
        api_key_id=None,
        http_status=200,
        request=request,
        response=response,
        spans=spans,
    )
    parsed = parse_trace_job_payload(payload)
    assert parsed[0] == "trace-1"
    assert parsed[4].model == "gpt-4o"
    assert len(parsed[6]) == 1
    assert parsed[6][0].span_name == "cache_lookup"
