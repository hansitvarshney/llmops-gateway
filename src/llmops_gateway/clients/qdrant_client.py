"""Shared async Qdrant client factory.

TODO(cache_layer): add collection bootstrap helper (create-if-missing with
the embedding provider's vector size + Cosine distance) called once at
startup for the currently configured embedding model.
"""

from qdrant_client import AsyncQdrantClient

from llmops_gateway.config.settings import Settings


def create_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
