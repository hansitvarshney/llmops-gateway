"""AnthropicProvider request/response mapping, using httpx.MockTransport so
no real network call is made."""

import json

import httpx
import pytest

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.providers.anthropic_provider import ANTHROPIC_BASE_URL, AnthropicProvider
from llmops_gateway.providers.base import ProviderRateLimitedError


def _install_transport(provider: AnthropicProvider, handler) -> None:
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=ANTHROPIC_BASE_URL
    )


def _request(**overrides) -> ChatRequest:
    defaults = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            ChatMessage(role="system", content="Be terse."),
            ChatMessage(role="user", content="hi"),
        ],
    }
    defaults.update(overrides)
    return ChatRequest(**defaults)


async def test_complete_extracts_system_prompt_and_maps_response() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "model": "claude-3-5-sonnet-20241022",
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        )

    provider = AnthropicProvider(api_key="test-key")
    _install_transport(provider, handler)

    response = await provider.complete(_request())
    assert response.message.content == "hello"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 4

    sent_payload = captured["body"]
    assert sent_payload["system"] == "Be terse."
    assert sent_payload["messages"] == [{"role": "user", "content": "hi"}]
    assert sent_payload["max_tokens"] == 4096  # DEFAULT_MAX_TOKENS fallback
    await provider.aclose()


async def test_complete_raises_rate_limited_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "5"}, json={"error": "rate limited"})

    provider = AnthropicProvider(api_key="test-key", max_retries=0)
    _install_transport(provider, handler)

    with pytest.raises(ProviderRateLimitedError) as exc_info:
        await provider.complete(_request())
    assert exc_info.value.retry_after_seconds == 5.0
    await provider.aclose()


async def test_stream_yields_content_block_deltas_and_stops_on_message_stop() -> None:
    sse_body = (
        "event: message_start\n"
        'data: {"type":"message_start"}\n\n'
        "event: content_block_delta\n"
        'data: {"delta":{"type":"text_delta","text":"Hel"}}\n\n'
        "event: content_block_delta\n"
        'data: {"delta":{"type":"text_delta","text":"lo"}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    provider = AnthropicProvider(api_key="test-key")
    _install_transport(provider, handler)

    chunks = [chunk async for chunk in provider.stream(_request(stream=True))]
    assert chunks == ["Hel", "lo"]
    await provider.aclose()


async def test_count_tokens_heuristic_fallback() -> None:
    provider = AnthropicProvider(api_key="test-key")
    usage = await provider.count_tokens(_request(), "hello world")
    assert usage.input_tokens >= 1
    assert usage.output_tokens >= 1
    await provider.aclose()
