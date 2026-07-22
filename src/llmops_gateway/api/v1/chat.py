"""OpenAI-compatible chat completions endpoint — the gateway's primary route.

Delegates all orchestration to GatewayService; this module is intentionally
thin (request/response marshalling + SSE framing + response headers only).
The cache layer is fully transparent to the caller: a cache hit and a live
provider call return the exact same `ChatResponse` shape/headers, distinguished
only by `cache_status` / `X-Cache-Status`.
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from llmops_gateway.api.deps import get_gateway_service
from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.services.gateway_service import (
    DEFAULT_TENANT_ID,
    GatewayService,
    StreamMetadata,
)

router = APIRouter(prefix="/v1", tags=["chat"])


def _resolve_trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "") or ""


def _resolve_tenant_id(request: Request) -> str:
    return getattr(request.state, "tenant_id", None) or DEFAULT_TENANT_ID


def _resolve_api_key_id(request: Request) -> str | None:
    return getattr(request.state, "api_key_id", None)


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    request: Request,
    payload: ChatRequest,
    response: Response,
    gateway: GatewayService = Depends(get_gateway_service),
) -> ChatResponse | StreamingResponse:
    trace_id = _resolve_trace_id(request)
    tenant_id = _resolve_tenant_id(request)
    api_key_id = _resolve_api_key_id(request)

    if not payload.stream:
        result = await gateway.handle_chat_completion(
            payload, trace_id=trace_id, tenant_id=tenant_id, api_key_id=api_key_id
        )
        response.headers["X-Trace-Id"] = result.trace_id
        response.headers["X-Cache-Status"] = result.cache_status.value
        response.headers["X-Request-Cost"] = f"{result.cost_usd:.6f}"
        if result.adapter_id:
            response.headers["X-Adapter-Id"] = result.adapter_id
        if result.model_alias:
            response.headers["X-Model-Alias"] = result.model_alias
            response.headers["X-Base-Model"] = result.model
        if result.adapter_stage:
            response.headers["X-Adapter-Stage"] = result.adapter_stage
        return result

    async def _sse() -> AsyncIterator[bytes]:
        async for item in gateway.handle_chat_completion_stream(
            payload, trace_id=trace_id, tenant_id=tenant_id, api_key_id=api_key_id
        ):
            if isinstance(item, StreamMetadata):
                event = {
                    "usage": item.response.usage.model_dump(),
                    "cost_usd": item.response.cost_usd,
                    "cache_status": item.response.cache_status.value,
                    "adapter_id": item.response.adapter_id,
                    "model_alias": item.response.model_alias,
                    "base_model": item.response.model,
                }
            else:
                event = {"choices": [{"delta": {"content": item}}]}
            yield f"data: {json.dumps(event)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"X-Trace-Id": trace_id},
    )
