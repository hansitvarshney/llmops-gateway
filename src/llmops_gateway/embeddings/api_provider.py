"""Opt-in EmbeddingProvider backed by an external embedding API (e.g. OpenAI).

Selected via `EMBEDDING_PROVIDER=api`. Trades an extra network round-trip for
embedding quality/consistency with the LLM's own semantic space. Must share
the same connection-pooled httpx client as the LLM provider adapters
(`clients.http_pool`) rather than opening ad hoc connections per call.

TODO(cache_layer): implement using the OpenAI embeddings endpoint (or make
the API family configurable), respecting the base timeout from BaseEmbeddingProvider.
"""

from llmops_gateway.embeddings.base import BaseEmbeddingProvider

_MODEL_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


class ApiEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, model_name: str = "text-embedding-3-small", **kwargs) -> None:
        super().__init__(**kwargs)
        self._model_name = model_name

    @property
    def model_id(self) -> str:
        return f"api-{self._model_name}"

    @property
    def dimension(self) -> int:
        return _MODEL_DIMENSIONS.get(self._model_name, 1536)

    async def _embed_impl(self, text: str) -> list[float]:
        raise NotImplementedError("Wire up the embeddings API call via the shared httpx pool")

    async def _embed_batch_impl(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Wire up the embeddings API call via the shared httpx pool")
