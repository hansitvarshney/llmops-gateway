"""Shared behavior for EmbeddingProvider implementations.

Wraps the abstract `_embed_impl`/`_embed_batch_impl` hooks with a hard
timeout so a degraded embedding backend (slow local model under load, or a
flaky external API) fails fast into a cache-bypass instead of blocking the
request path. Concrete providers only need to implement the `_impl` methods.
"""

import asyncio

from llmops_gateway.domain.interfaces.embedding_provider import EmbeddingProvider

DEFAULT_EMBED_TIMEOUT_SECONDS = 0.5


class EmbeddingTimeoutError(Exception):
    """Raised when embedding generation exceeds its latency budget."""


class BaseEmbeddingProvider(EmbeddingProvider):
    def __init__(self, timeout_seconds: float = DEFAULT_EMBED_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    async def embed(self, text: str) -> list[float]:
        try:
            return await asyncio.wait_for(self._embed_impl(text), timeout=self._timeout_seconds)
        except TimeoutError as exc:
            raise EmbeddingTimeoutError(
                f"{self.model_id} embedding exceeded {self._timeout_seconds}s budget"
            ) from exc

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_batch_impl(texts)

    async def _embed_impl(self, text: str) -> list[float]:
        raise NotImplementedError

    async def _embed_batch_impl(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
