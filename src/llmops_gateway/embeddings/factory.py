"""Resolves the active EmbeddingProvider from settings.

This is the single place that knows about the `EmbeddingProviderKind` enum;
everything downstream (CacheService, GatewayService) only ever sees the
`EmbeddingProvider` interface.
"""

from functools import lru_cache

from llmops_gateway.config.settings import EmbeddingProviderKind, Settings, get_settings
from llmops_gateway.domain.interfaces.embedding_provider import EmbeddingProvider
from llmops_gateway.embeddings.api_provider import ApiEmbeddingProvider
from llmops_gateway.embeddings.local_provider import LocalEmbeddingProvider


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider is EmbeddingProviderKind.LOCAL:
        return LocalEmbeddingProvider(model_name=settings.embedding_local_model_name)
    if settings.embedding_provider is EmbeddingProviderKind.API:
        return ApiEmbeddingProvider(model_name=settings.embedding_api_model_name)
    raise ValueError(f"Unknown embedding provider kind: {settings.embedding_provider}")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return build_embedding_provider(get_settings())
