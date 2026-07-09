"""Selects and calls an upstream provider with automatic cross-provider fallback.

For each request, `_resolve_attempts` builds an ordered list of
(provider, model_to_use) pairs:
  1. The model's native provider (e.g. OpenAI for 'gpt-4o'), using the
     exact requested model — unless `request.provider_override` pins a
     specific provider, in which case that's the only attempt.
  2. Every other provider in `settings.provider_fallback_chain`, each
     mapped to its configured cross-provider equivalent model via
     `ProviderRegistry.resolve_equivalent_model` (e.g. 'gpt-4o' ->
     'claude-3-5-sonnet-20241022'). Providers with no configured mapping
     for this model are skipped — we never guess an equivalent model.

`RoutingService` only moves to the next attempt when a provider raises
`ProviderError` (its own retry budget + circuit breaker already exhausted
inside BaseLLMProvider) — it never retries a provider itself. For streaming,
fallback is only attempted if the failing provider hasn't yielded any tokens
yet; once output has reached the caller, the error is raised as-is rather
than risking duplicated content from a second provider.
"""

from collections.abc import AsyncIterator, Callable

import structlog

from llmops_gateway.config.settings import Settings
from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.domain.interfaces.llm_provider import LLMProvider
from llmops_gateway.providers.base import ProviderError
from llmops_gateway.providers.registry import ProviderRegistry

logger = structlog.get_logger(__name__)


class AllProvidersExhaustedError(Exception):
    """Raised when every attempted provider in the fallback chain has failed
    (or no provider/mapping exists at all for the requested model)."""

    def __init__(self, attempts: list[tuple[str, Exception]]) -> None:
        if attempts:
            summary = "; ".join(f"{name}: {exc}" for name, exc in attempts)
            message = f"All providers exhausted: {summary}"
        else:
            message = "No provider available for the requested model"
        super().__init__(message)
        self.attempts = attempts


class RoutingService:
    def __init__(self, registry: ProviderRegistry, settings: Settings) -> None:
        self._registry = registry
        self._settings = settings

    def _resolve_attempts(self, request: ChatRequest) -> list[tuple[LLMProvider, str]]:
        if request.provider_override:
            return [(self._registry.get(request.provider_override), request.model)]

        ordered_names: list[str] = []
        primary = self._registry.find_supporting(request.model)
        if primary is not None:
            ordered_names.append(primary.name)
        for name in self._settings.provider_fallback_chain:
            if name not in ordered_names:
                ordered_names.append(name)

        attempts: list[tuple[LLMProvider, str]] = []
        for name in ordered_names:
            provider = self._registry.try_get(name)
            if provider is None:
                continue
            if provider.supports_model(request.model):
                attempts.append((provider, request.model))
                continue
            equivalent_model = self._registry.resolve_equivalent_model(request.model, name)
            if equivalent_model is not None:
                attempts.append((provider, equivalent_model))
        return attempts

    @staticmethod
    def _attempt_request(request: ChatRequest, model: str) -> ChatRequest:
        return request if model == request.model else request.model_copy(update={"model": model})

    async def complete(self, request: ChatRequest) -> ChatResponse:
        attempts = self._resolve_attempts(request)
        errors: list[tuple[str, Exception]] = []

        for provider, model in attempts:
            attempt_request = self._attempt_request(request, model)
            try:
                return await provider.complete(attempt_request)
            except ProviderError as exc:
                logger.warning(
                    "provider_attempt_failed", provider=provider.name, model=model, error=str(exc)
                )
                errors.append((provider.name, exc))
                continue

        raise AllProvidersExhaustedError(errors)

    async def stream(
        self,
        request: ChatRequest,
        on_provider_selected: Callable[[LLMProvider, ChatRequest], None] | None = None,
    ) -> AsyncIterator[str]:
        """`on_provider_selected`, if given, is invoked exactly once — right
        before the first chunk is yielded — with the provider that ended up
        serving the stream and the (possibly model-remapped) request sent to
        it. Callers use this to attribute usage/cost correctly after the
        stream completes, since a plain `AsyncIterator[str]` carries no
        provider metadata on its own.
        """
        attempts = self._resolve_attempts(request)
        errors: list[tuple[str, Exception]] = []

        for provider, model in attempts:
            attempt_request = self._attempt_request(request, model)
            yielded_any = False
            try:
                async for chunk in provider.stream(attempt_request):
                    if not yielded_any and on_provider_selected is not None:
                        on_provider_selected(provider, attempt_request)
                    yielded_any = True
                    yield chunk
                return
            except ProviderError as exc:
                logger.warning(
                    "provider_stream_attempt_failed",
                    provider=provider.name,
                    model=model,
                    error=str(exc),
                    partial_output_sent=yielded_any,
                )
                errors.append((provider.name, exc))
                if yielded_any:
                    raise
                continue

        raise AllProvidersExhaustedError(errors)
