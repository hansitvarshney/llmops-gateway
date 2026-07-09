"""Anthropic adapter implementing LLMProvider against the Messages API.

Two translation quirks vs. OpenAI drive most of this file:
  - Anthropic has no `system` role inside `messages`; system prompts are a
    top-level `system` string, so they're extracted out of ChatRequest here.
  - `max_tokens` is a required field for Anthropic (optional for OpenAI), so
    a default is substituted when the caller didn't specify one.

Streaming uses named SSE events (`content_block_delta`, `message_stop`, ...)
rather than OpenAI's single implicit event type, so the parser tracks the
current `event:` line to interpret the following `data:` line correctly.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from json import JSONDecodeError
from json import loads as json_loads

import httpx
import structlog

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

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096  # Anthropic requires max_tokens; OpenAI does not.


def _retry_after_from_headers(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str = ANTHROPIC_BASE_URL, **kwargs) -> None:
        super().__init__(**kwargs)
        self._client = create_http_client(
            base_url,
            timeout_seconds=self._request_timeout_seconds,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )

    def supports_model(self, model: str) -> bool:
        return model.startswith("claude-")

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        conversation = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        payload: dict = {
            "model": request.model,
            "messages": conversation,
            "max_tokens": request.max_tokens or DEFAULT_MAX_TOKENS,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        if request.stop:
            payload["stop_sequences"] = request.stop
        return payload

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            raise ProviderRateLimitedError(
                retry_after_seconds=_retry_after_from_headers(response.headers)
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"Anthropic returned HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )

    async def _post(self, payload: dict) -> httpx.Response:
        try:
            return await self._client.post("/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Anthropic request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"Failed to connect to Anthropic: {exc}") from exc

    async def _complete_impl(self, request: ChatRequest) -> ChatResponse:
        payload = self._build_payload(request, stream=False)
        response = await self._post(payload)
        self._raise_for_status(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"Anthropic returned invalid JSON: {exc}", status_code=response.status_code
            ) from exc

        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage_raw = data.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
        )
        return ChatResponse(
            id=data.get("id", ""),
            model=data.get("model", request.model),
            provider=self.name,
            message=ChatMessage(role="assistant", content=text),
            usage=usage,
            cost_usd=0.0,
            trace_id="",
            created_at=datetime.now(UTC),
            latency_ms=0.0,
        )

    async def _stream_impl(self, request: ChatRequest) -> AsyncIterator[str]:
        payload = self._build_payload(request, stream=True)
        try:
            async with self._client.stream("POST", "/messages", json=payload) as response:
                if response.status_code != 200:
                    await response.aread()
                    self._raise_for_status(response)

                current_event: str | None = None
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line[len("event:") :].strip()
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_str = line[len("data:") :].strip()
                    try:
                        event_data = json_loads(data_str)
                    except JSONDecodeError:
                        continue

                    if current_event == "content_block_delta":
                        delta = event_data.get("delta", {})
                        text = delta.get("text")
                        if text:
                            yield text
                    elif current_event == "error":
                        error = event_data.get("error", {})
                        raise ProviderResponseError(
                            f"Anthropic stream error: {error.get('message', event_data)}",
                            status_code=response.status_code,
                        )
                    elif current_event == "message_stop":
                        break
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Anthropic stream timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"Failed to connect to Anthropic: {exc}") from exc

    async def count_tokens(self, request: ChatRequest, completion_text: str) -> TokenUsage:
        # Fallback only — the Messages API returns a `usage` block on every
        # non-streaming response and in the final `message_delta` streaming
        # event, so this heuristic (~4 chars/token) is rarely exercised.
        prompt_chars = sum(len(m.content) for m in request.messages)
        completion_chars = len(completion_text)
        return TokenUsage(
            input_tokens=max(1, prompt_chars // 4),
            output_tokens=max(1, completion_chars // 4),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
