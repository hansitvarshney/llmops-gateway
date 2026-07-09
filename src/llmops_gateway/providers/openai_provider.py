"""OpenAI adapter implementing LLMProvider against the chat.completions API.

Non-streaming and streaming (SSE, with `stream_options.include_usage` so the
final chunk still carries token counts) both translate to/from the
provider-agnostic ChatRequest/ChatResponse shapes. `cost_usd`, `trace_id`,
and `latency_ms` on the returned ChatResponse are left as placeholders here
deliberately — pricing/tracing are cross-cutting concerns owned by
CostService/TracingService in GatewayService, not the provider adapter.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from functools import lru_cache

import httpx
import structlog
import tiktoken

from llmops_gateway.clients.http_pool import create_http_client
from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.providers.base import (
    BaseLLMProvider,
    ProviderConnectionError,
    ProviderRateLimitedError,
    ProviderResponseError,
    ProviderTimeoutError,
)

logger = structlog.get_logger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TOKENIZER_ENCODING = "cl100k_base"


@lru_cache(maxsize=32)
def _encoding_for_model(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(DEFAULT_TOKENIZER_ENCODING)


def _retry_after_from_headers(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def __init__(self, api_key: str, base_url: str = OPENAI_BASE_URL, **kwargs) -> None:
        super().__init__(**kwargs)
        self._client = create_http_client(
            base_url,
            timeout_seconds=self._request_timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def supports_model(self, model: str) -> bool:
        return model.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict:
        payload: dict = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": stream,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stop:
            payload["stop"] = request.stop
        if stream:
            # Ensures the final SSE chunk carries a `usage` object even in
            # streaming mode, so we don't have to rely on the tiktoken
            # fallback in count_tokens() for the common case.
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            raise ProviderRateLimitedError(
                retry_after_seconds=_retry_after_from_headers(response.headers)
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"OpenAI returned HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )

    async def _post(self, payload: dict) -> httpx.Response:
        try:
            return await self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"OpenAI request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"Failed to connect to OpenAI: {exc}") from exc

    async def _complete_impl(self, request: ChatRequest) -> ChatResponse:
        payload = self._build_payload(request, stream=False)
        response = await self._post(payload)
        self._raise_for_status(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"OpenAI returned invalid JSON: {exc}", status_code=response.status_code
            ) from exc

        choice = data["choices"][0]
        usage_raw = data.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_raw.get("prompt_tokens", 0),
            output_tokens=usage_raw.get("completion_tokens", 0),
        )
        return ChatResponse(
            id=data.get("id", str(uuid.uuid4())),
            model=data.get("model", request.model),
            provider=self.name,
            message=ChatMessage(role="assistant", content=choice["message"]["content"] or ""),
            usage=usage,
            cost_usd=0.0,
            trace_id="",
            created_at=datetime.now(UTC),
            latency_ms=0.0,
        )

    async def _stream_impl(self, request: ChatRequest) -> AsyncIterator[str]:
        payload = self._build_payload(request, stream=True)
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    await response.aread()
                    self._raise_for_status(response)

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue  # e.g. the trailing usage-only chunk
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"OpenAI stream timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"Failed to connect to OpenAI: {exc}") from exc

    async def count_tokens(self, request: ChatRequest, completion_text: str) -> TokenUsage:
        def _count() -> TokenUsage:
            encoding = _encoding_for_model(request.model)
            prompt_tokens = sum(
                len(encoding.encode(f"{m.role}:{m.content}")) for m in request.messages
            )
            completion_tokens = len(encoding.encode(completion_text))
            return TokenUsage(input_tokens=prompt_tokens, output_tokens=completion_tokens)

        # tiktoken is CPU-bound (pure Python/C encode loop); offload so a
        # large prompt never blocks the event loop.
        return await asyncio.to_thread(_count)

    async def aclose(self) -> None:
        await self._client.aclose()
