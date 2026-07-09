"""Factory + fallback-chain resolution for LLMProvider adapters.

`RoutingService` asks this registry which provider natively serves a given
model (`find_supporting`) and which cross-provider equivalent model to use
when falling back (`resolve_equivalent_model`); it stays the only place that
knows how to construct each concrete adapter or read the fallback map.
"""

from functools import lru_cache

from llmops_gateway.config.settings import Settings, get_settings
from llmops_gateway.domain.interfaces.llm_provider import LLMProvider
from llmops_gateway.domain.value_objects.model_identifier import ModelIdentifier
from llmops_gateway.providers.anthropic_provider import AnthropicProvider
from llmops_gateway.providers.openai_provider import OpenAIProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._providers: dict[str, LLMProvider] = {}

        common_kwargs = {
            "max_retries": settings.provider_max_retries,
            "request_timeout_seconds": settings.provider_request_timeout_seconds,
            "circuit_failure_threshold": settings.provider_circuit_failure_threshold,
            "circuit_cooldown_seconds": settings.provider_circuit_cooldown_seconds,
        }
        if settings.openai_api_key:
            self._providers["openai"] = OpenAIProvider(
                api_key=settings.openai_api_key, **common_kwargs
            )
        if settings.anthropic_api_key:
            self._providers["anthropic"] = AnthropicProvider(
                api_key=settings.anthropic_api_key, **common_kwargs
            )

    def get(self, name: str) -> LLMProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ValueError(f"No provider registered for {name!r}") from exc

    def try_get(self, name: str) -> LLMProvider | None:
        return self._providers.get(name)

    def find_supporting(self, model: str) -> LLMProvider | None:
        """The provider that natively serves `model` (e.g. OpenAI for 'gpt-4o')."""
        for provider in self._providers.values():
            if provider.supports_model(model):
                return provider
        return None

    def resolve_equivalent_model(self, model: str, target_provider: str) -> str | None:
        """Cross-provider equivalent-model lookup for fallback routing, e.g.
        `resolve_equivalent_model("gpt-4o", "anthropic")` -> "claude-3-5-sonnet-20241022".

        Returns None when `model`'s native provider is unknown or no mapping
        to `target_provider` is configured — callers should skip that
        provider in the fallback chain in that case.
        """
        source_provider = self.find_supporting(model)
        if source_provider is None:
            return None
        key = str(ModelIdentifier(provider=source_provider.name, model=model))
        mapped = self._settings.provider_model_fallback_map.get(key)
        if mapped is None:
            return None
        mapped_identifier = ModelIdentifier.parse(mapped)
        if mapped_identifier.provider != target_provider:
            return None
        return mapped_identifier.model

    def fallback_chain(self, override: str | None = None) -> list[LLMProvider]:
        if override:
            return [self.get(override)]
        return [
            provider
            for name in self._settings.provider_fallback_chain
            if (provider := self._providers.get(name)) is not None
        ]

    def __iter__(self):
        return iter(self._providers.values())

    async def aclose_all(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(get_settings())
