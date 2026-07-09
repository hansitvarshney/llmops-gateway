"""OpenAIProvider request/response mapping, using httpx.MockTransport so no
real network call is made."""

import httpx
import pytest

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.providers.base import ProviderRateLimitedError, ProviderResponseError
from llmops_gateway.providers.openai_provider import OPENAI_BASE_URL, OpenAIProvider


def _install_transport(provider: OpenAIProvider, handler) -> None:
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=OPENAI_BASE_URL
    )


def _request(**overrides) -> ChatRequest:
    defaults = {"model": "gpt-4o", "messages": [ChatMessage(role="user", content="hi")]}
    defaults.update(overrides)
    return ChatRequest(**defaults)


async def test_complete_maps_openai_response_to_chat_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "gpt-4o",
                "choices": [{"message": {"role": "assistant", "content": "hello there"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    provider = OpenAIProvider(api_key="test-key")
    _install_transport(provider, handler)

    response = await provider.complete(_request())
    assert response.message.content == "hello there"
    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens == 3
    assert response.provider == "openai"
    await provider.aclose()


async def test_complete_raises_rate_limited_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "2"}, json={"error": "rate limited"})

    provider = OpenAIProvider(api_key="test-key", max_retries=0)
    _install_transport(provider, handler)

    with pytest.raises(ProviderRateLimitedError) as exc_info:
        await provider.complete(_request())
    assert exc_info.value.retry_after_seconds == 2.0
    await provider.aclose()


async def test_complete_raises_non_retryable_on_400() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    provider = OpenAIProvider(api_key="test-key", max_retries=3)
    _install_transport(provider, handler)

    with pytest.raises(ProviderResponseError) as exc_info:
        await provider.complete(_request())
    assert exc_info.value.retryable is False
    await provider.aclose()


async def test_stream_yields_text_deltas_and_ignores_usage_only_chunk() -> None:
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    provider = OpenAIProvider(api_key="test-key")
    _install_transport(provider, handler)

    chunks = [chunk async for chunk in provider.stream(_request(stream=True))]
    assert chunks == ["Hel", "lo"]
    await provider.aclose()


async def test_count_tokens_uses_tiktoken() -> None:
    provider = OpenAIProvider(api_key="test-key")
    usage = await provider.count_tokens(_request(), "hello world")
    assert usage.input_tokens > 0
    assert usage.output_tokens > 0
    await provider.aclose()
