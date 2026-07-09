"""Default EmbeddingProvider: in-process sentence-transformers model.

Zero network hop, so it's the lowest-latency option for the Layer-2 semantic
cache lookup and is the default in `Settings.embedding_provider`. The model
is loaded once — eagerly via `warm_up()` at application startup rather than
lazily on the first request, since a cold model load can take several
seconds and must never be paid for by a real user's request latency budget.
Both loading and inference (CPU-bound) are offloaded to a thread so neither
ever blocks the asyncio event loop.
"""

import asyncio

import structlog

from llmops_gateway.embeddings.base import BaseEmbeddingProvider

logger = structlog.get_logger(__name__)

# Known output dimensionality for common sentence-transformers models, used
# to size the Qdrant collection before the model has actually been loaded
# (e.g. if a caller reads `.dimension` prior to `warm_up()`). Overwritten
# with the model's real reported dimension once it's loaded.
_KNOWN_MODEL_DIMENSIONS = {
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    "multi-qa-MiniLM-L6-cos-v1": 384,
    "paraphrase-MiniLM-L6-v2": 384,
}
_DEFAULT_DIMENSION_FALLBACK = 384


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", **kwargs) -> None:
        super().__init__(**kwargs)
        self._model_name = model_name
        self._model = None
        self._dimension = _KNOWN_MODEL_DIMENSIONS.get(model_name, _DEFAULT_DIMENSION_FALLBACK)
        self._load_lock = asyncio.Lock()

    @property
    def model_id(self) -> str:
        return f"local-{self._model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def warm_up(self) -> None:
        await self._ensure_model_loaded()

    async def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            logger.info("local_embedding_model_loading", model_name=self._model_name)
            self._model = await asyncio.to_thread(self._load_model)
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                "local_embedding_model_loaded",
                model_name=self._model_name,
                dimension=self._dimension,
            )

    def _load_model(self):
        # Imported lazily (not at module import time) so the heavy
        # sentence-transformers/torch dependency chain is only paid for
        # when local embeddings are actually configured/used.
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self._model_name)

    async def _embed_impl(self, text: str) -> list[float]:
        await self._ensure_model_loaded()
        return await asyncio.to_thread(self._encode_one, text)

    async def _embed_batch_impl(self, texts: list[str]) -> list[list[float]]:
        await self._ensure_model_loaded()
        return await asyncio.to_thread(self._encode_many, texts)

    def _encode_one(self, text: str) -> list[float]:
        vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def _encode_many(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]
