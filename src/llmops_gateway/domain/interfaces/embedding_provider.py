"""Pluggable embedding backend for the Layer-2 semantic cache.

Two implementations ship out of the box (see `llmops_gateway.embeddings`):
  - `LocalEmbeddingProvider`  (default) — in-process sentence-transformers,
    zero network hop, lowest latency on the caching critical path.
  - `ApiEmbeddingProvider`    (opt-in)  — calls an external embedding API
    (e.g. OpenAI text-embedding-3-small) for higher-fidelity vectors at the
    cost of an extra network round-trip.

Selection is purely a settings flag (`EMBEDDING_PROVIDER=local|api`); nothing
above this interface (CacheService, GatewayService) needs to know which
implementation is active. `model_id` is used to namespace/version the Qdrant
collection so vectors from different embedding models are never compared
against each other.
"""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str:
        """Stable identifier for the embedding model, e.g. 'minilm-l6-v2'.

        Used to namespace Qdrant collections so switching providers/models
        can never silently mix incompatible vector spaces.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector dimensionality, required to configure the Qdrant collection."""
        raise NotImplementedError

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed a single piece of text. Must enforce its own timeout internally
        so a slow embedding backend degrades to a cache-bypass rather than
        blocking the request indefinitely."""
        raise NotImplementedError

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batched embedding, used by background backfill/migration jobs."""
        raise NotImplementedError

    async def warm_up(self) -> None:
        """Optional hook to eagerly initialize the backend — e.g. load a
        local model into memory — at application startup rather than
        paying that cost on whichever request happens to arrive first.
        Default no-op; only `LocalEmbeddingProvider` needs to override this."""
        return None
