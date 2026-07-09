"""Exercises BaseLLMProvider's retry/backoff/circuit-breaker wrapper via a
minimal fake adapter, independent of any real HTTP provider."""

from datetime import UTC, datetime

import pytest

from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.providers.base import (
    BaseLLMProvider,
    ProviderResponseError,
    ProviderUnavailableError,
)


class _FakeProvider(BaseLLMProvider):
    name = "fake"

    def __init__(self, complete_side_effects=None, stream_side_effects=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._complete_side_effects = list(complete_side_effects or [])
        self._stream_side_effects = list(stream_side_effects or [])
        self.complete_calls = 0
        self.stream_calls = 0

    def supports_model(self, model: str) -> bool:
        return True

    async def _complete_impl(self, request: ChatRequest) -> ChatResponse:
        self.complete_calls += 1
        effect = self._complete_side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    async def _stream_impl(self, request: ChatRequest):
        self.stream_calls += 1
        effect = self._stream_side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        if hasattr(effect, "__aiter__"):
            async for chunk in effect:
                yield chunk
        else:
            for chunk in effect:
                yield chunk

    async def count_tokens(self, request: ChatRequest, completion_text: str) -> TokenUsage:
        return TokenUsage(input_tokens=0, output_tokens=0)


def _fake_response() -> ChatResponse:
    return ChatResponse(
        id="1",
        model="m",
        provider="fake",
        message=ChatMessage(role="assistant", content="hi"),
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.0,
        trace_id="",
        created_at=datetime.now(UTC),
        latency_ms=0.0,
    )


def _request() -> ChatRequest:
    return ChatRequest(model="m", messages=[ChatMessage(role="user", content="hi")])


async def test_complete_retries_transient_error_then_succeeds() -> None:
    provider = _FakeProvider(
        complete_side_effects=[ProviderResponseError("boom", status_code=500), _fake_response()],
        max_retries=3,
    )
    result = await provider.complete(_request())
    assert result.message.content == "hi"
    assert provider.complete_calls == 2


async def test_complete_raises_after_exhausting_retries() -> None:
    provider = _FakeProvider(
        complete_side_effects=[
            ProviderResponseError("boom", status_code=500),
            ProviderResponseError("boom", status_code=500),
        ],
        max_retries=1,
    )
    with pytest.raises(ProviderResponseError):
        await provider.complete(_request())
    assert provider.complete_calls == 2  # initial attempt + 1 retry


async def test_complete_does_not_retry_non_retryable_error() -> None:
    provider = _FakeProvider(
        complete_side_effects=[ProviderResponseError("bad request", status_code=400)],
        max_retries=5,
    )
    with pytest.raises(ProviderResponseError):
        await provider.complete(_request())
    assert provider.complete_calls == 1


async def test_circuit_opens_and_fails_fast_on_subsequent_calls() -> None:
    provider = _FakeProvider(
        complete_side_effects=[ProviderResponseError("boom", status_code=500)] * 10,
        max_retries=0,
        circuit_failure_threshold=2,
    )
    with pytest.raises(ProviderResponseError):
        await provider.complete(_request())
    with pytest.raises(ProviderResponseError):
        await provider.complete(_request())
    with pytest.raises(ProviderUnavailableError):
        await provider.complete(_request())
    assert provider.complete_calls == 2  # third call never reached _complete_impl


async def test_stream_does_not_retry_after_partial_output() -> None:
    async def _gen_that_fails_midway():
        yield "hello "
        raise ProviderResponseError("dropped", status_code=500)

    provider = _FakeProvider(stream_side_effects=[_gen_that_fails_midway()], max_retries=5)
    chunks = []
    with pytest.raises(ProviderResponseError):
        async for chunk in provider.stream(_request()):
            chunks.append(chunk)
    assert chunks == ["hello "]
    assert provider.stream_calls == 1


async def test_stream_retries_before_any_output_yielded() -> None:
    provider = _FakeProvider(
        stream_side_effects=[
            ProviderResponseError("boom", status_code=500),
            iter(["a", "b"]),
        ],
        max_retries=3,
    )
    chunks = [chunk async for chunk in provider.stream(_request())]
    assert chunks == ["a", "b"]
    assert provider.stream_calls == 2
