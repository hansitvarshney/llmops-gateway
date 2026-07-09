"""RoutingService fallback-chain behavior, using stub providers/registry so
no real network or ProviderRegistry construction is needed."""

from datetime import UTC, datetime

import pytest

from llmops_gateway.config.settings import Settings
from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.providers.base import BaseLLMProvider, ProviderResponseError
from llmops_gateway.services.routing_service import AllProvidersExhaustedError, RoutingService


class _StubProvider(BaseLLMProvider):
    def __init__(
        self,
        name: str,
        model_prefix: str,
        complete_result: ChatResponse | None = None,
        complete_error: Exception | None = None,
        stream_chunks: list[str] | None = None,
        stream_error: Exception | None = None,
        fail_after_first_chunk: bool = False,
    ) -> None:
        super().__init__(max_retries=0)
        self.name = name
        self._model_prefix = model_prefix
        self._complete_result = complete_result
        self._complete_error = complete_error
        self._stream_chunks = stream_chunks or []
        self._stream_error = stream_error
        self._fail_after_first_chunk = fail_after_first_chunk
        self.complete_calls = 0
        self.stream_calls = 0

    def supports_model(self, model: str) -> bool:
        return model.startswith(self._model_prefix)

    async def _complete_impl(self, request: ChatRequest) -> ChatResponse:
        self.complete_calls += 1
        if self._complete_error:
            raise self._complete_error
        assert self._complete_result is not None
        return self._complete_result

    async def _stream_impl(self, request: ChatRequest):
        self.stream_calls += 1
        for i, chunk in enumerate(self._stream_chunks):
            yield chunk
            if self._fail_after_first_chunk and i == 0 and self._stream_error:
                raise self._stream_error
        if self._stream_error and not self._fail_after_first_chunk:
            raise self._stream_error

    async def count_tokens(self, request: ChatRequest, completion_text: str) -> TokenUsage:
        return TokenUsage(input_tokens=0, output_tokens=0)


class _StubRegistry:
    def __init__(self, providers: dict[str, _StubProvider]) -> None:
        self._providers = providers

    def get(self, name: str) -> _StubProvider:
        return self._providers[name]

    def try_get(self, name: str) -> _StubProvider | None:
        return self._providers.get(name)

    def find_supporting(self, model: str) -> _StubProvider | None:
        for provider in self._providers.values():
            if provider.supports_model(model):
                return provider
        return None

    def resolve_equivalent_model(self, model: str, target_provider: str) -> str | None:
        if target_provider == "anthropic" and model == "gpt-4o":
            return "claude-3-5-sonnet-20241022"
        return None


def _response(provider_name: str = "openai", content: str = "hi") -> ChatResponse:
    return ChatResponse(
        id="1",
        model="m",
        provider=provider_name,
        message=ChatMessage(role="assistant", content=content),
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.0,
        trace_id="",
        created_at=datetime.now(UTC),
        latency_ms=0.0,
    )


def _request(model: str = "gpt-4o") -> ChatRequest:
    return ChatRequest(model=model, messages=[ChatMessage(role="user", content="hi")])


async def test_complete_uses_primary_provider_when_healthy() -> None:
    openai = _StubProvider("openai", "gpt-", complete_result=_response("openai"))
    anthropic = _StubProvider("anthropic", "claude-", complete_result=_response("anthropic"))
    routing = RoutingService(_StubRegistry({"openai": openai, "anthropic": anthropic}), Settings())

    result = await routing.complete(_request("gpt-4o"))
    assert result.provider == "openai"
    assert openai.complete_calls == 1
    assert anthropic.complete_calls == 0


async def test_complete_falls_back_to_next_provider_on_failure() -> None:
    openai = _StubProvider(
        "openai", "gpt-", complete_error=ProviderResponseError("down", status_code=500)
    )
    anthropic = _StubProvider("anthropic", "claude-", complete_result=_response("anthropic"))
    routing = RoutingService(_StubRegistry({"openai": openai, "anthropic": anthropic}), Settings())

    result = await routing.complete(_request("gpt-4o"))
    assert result.provider == "anthropic"
    assert openai.complete_calls == 1
    assert anthropic.complete_calls == 1


async def test_complete_raises_when_all_providers_exhausted() -> None:
    openai = _StubProvider(
        "openai", "gpt-", complete_error=ProviderResponseError("down", status_code=500)
    )
    anthropic = _StubProvider(
        "anthropic", "claude-", complete_error=ProviderResponseError("down too", status_code=500)
    )
    routing = RoutingService(_StubRegistry({"openai": openai, "anthropic": anthropic}), Settings())

    with pytest.raises(AllProvidersExhaustedError):
        await routing.complete(_request("gpt-4o"))


async def test_stream_falls_back_before_any_output_sent() -> None:
    openai = _StubProvider(
        "openai", "gpt-", stream_error=ProviderResponseError("down", status_code=500)
    )
    anthropic = _StubProvider("anthropic", "claude-", stream_chunks=["a", "b"])
    routing = RoutingService(_StubRegistry({"openai": openai, "anthropic": anthropic}), Settings())

    chunks = [chunk async for chunk in routing.stream(_request("gpt-4o"))]
    assert chunks == ["a", "b"]
    assert openai.stream_calls == 1
    assert anthropic.stream_calls == 1


async def test_stream_does_not_fall_back_after_partial_output_sent() -> None:
    openai = _StubProvider(
        "openai",
        "gpt-",
        stream_chunks=["partial "],
        stream_error=ProviderResponseError("dropped", status_code=500),
        fail_after_first_chunk=True,
    )
    anthropic = _StubProvider("anthropic", "claude-", stream_chunks=["should", "not", "be", "used"])
    routing = RoutingService(_StubRegistry({"openai": openai, "anthropic": anthropic}), Settings())

    chunks = []
    with pytest.raises(ProviderResponseError):
        async for chunk in routing.stream(_request("gpt-4o")):
            chunks.append(chunk)
    assert chunks == ["partial "]
    assert anthropic.stream_calls == 0
