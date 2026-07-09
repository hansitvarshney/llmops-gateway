"""Layer 2: Qdrant semantic-similarity cache.

Implements the CacheStore port. Embeds the prompt via the configured
EmbeddingProvider, then searches a collection namespaced by
`semantic_cache__{embedding_model_id}` (so switching embedding models can
never silently mix incompatible vector spaces), filtered on
(tenant_id, model_family, params_hash) so a hit is only ever returned for a
request that is truly equivalent — same tenant, same model, same generation
parameters — differing only in prompt *wording*. A hit additionally requires
cosine similarity to clear `similarity_threshold` (default 0.95).

The entire get()/set() operation (embed + Qdrant round-trip) is wrapped in a
single hard timeout and a catch-all exception handler: per the architecture
plan's "Qdrant latency exceeding LLM latency savings" mitigation, a slow or
unavailable semantic cache must degrade to a plain MISS rather than add
latency to — or ever break — the request path.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from qdrant_client import models as qmodels

from llmops_gateway.caching.hashing import normalize_prompt
from llmops_gateway.caching.hashing import params_hash as compute_params_hash
from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.domain.interfaces.cache_store import CacheStore
from llmops_gateway.domain.interfaces.embedding_provider import EmbeddingProvider
from llmops_gateway.domain.value_objects.cache_status import CacheStatus

logger = structlog.get_logger(__name__)

DEFAULT_WRITE_TIMEOUT_SECONDS = 2.0
MAX_STORED_PROMPT_CHARS = 2000
FILTERED_PAYLOAD_FIELDS = ("tenant_id", "model_family", "params_hash")


def collection_name(embedding_model_id: str) -> str:
    """Namespaces the Qdrant collection by embedding model so vectors from
    different models/dimensions are never compared against each other."""
    safe = embedding_model_id.replace(".", "_").replace(":", "_").replace("-", "_")
    return f"semantic_cache__{safe}"


class QdrantSemanticCache(CacheStore):
    def __init__(
        self,
        qdrant_client,
        embedding_provider: EmbeddingProvider,
        similarity_threshold: float,
        search_timeout_ms: int,
        write_timeout_seconds: float = DEFAULT_WRITE_TIMEOUT_SECONDS,
    ) -> None:
        self._qdrant = qdrant_client
        self._embeddings = embedding_provider
        self._similarity_threshold = similarity_threshold
        self._search_timeout_seconds = search_timeout_ms / 1000
        self._write_timeout_seconds = write_timeout_seconds
        self._collection = collection_name(embedding_provider.model_id)
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()

    async def ensure_collection(self) -> None:
        """Create-if-missing, with the embedding provider's vector size +
        Cosine distance, plus payload indexes for every field the search
        filter touches. Idempotent; safe to call from every get()/set()."""
        if self._bootstrapped:
            return
        async with self._bootstrap_lock:
            if self._bootstrapped:
                return
            exists = await self._qdrant.collection_exists(self._collection)
            if not exists:
                await self._qdrant.create_collection(
                    collection_name=self._collection,
                    vectors_config=qmodels.VectorParams(
                        size=self._embeddings.dimension, distance=qmodels.Distance.COSINE
                    ),
                )
                for field_name in FILTERED_PAYLOAD_FIELDS:
                    await self._qdrant.create_payload_index(
                        collection_name=self._collection,
                        field_name=field_name,
                        field_schema=qmodels.PayloadSchemaType.KEYWORD,
                    )
                logger.info("semantic_cache_collection_created", collection=self._collection)
            self._bootstrapped = True

    async def get(self, request: ChatRequest, *, tenant_id: str) -> ChatResponse | None:
        try:
            return await asyncio.wait_for(
                self._get_impl(request, tenant_id), timeout=self._search_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - cache failures must never break the request path
            logger.warning(
                "semantic_cache_get_failed", error=str(exc), error_type=type(exc).__name__
            )
            return None

    async def _get_impl(self, request: ChatRequest, tenant_id: str) -> ChatResponse | None:
        await self.ensure_collection()
        vector = await self._embeddings.embed(normalize_prompt(request.canonical_prompt()))

        result = await self._qdrant.query_points(
            collection_name=self._collection,
            query=vector,
            query_filter=self._build_filter(request, tenant_id),
            limit=1,
            score_threshold=self._similarity_threshold,
            with_payload=True,
        )
        if not result.points:
            return None

        best = result.points[0]
        payload = best.payload or {}
        response_data = payload.get("response")
        if response_data is None:
            return None

        try:
            response = ChatResponse.model_validate(response_data)
        except ValueError as exc:
            logger.warning("semantic_cache_corrupt_entry", point_id=str(best.id), error=str(exc))
            return None

        logger.info(
            "semantic_cache_hit",
            collection=self._collection,
            score=round(best.score, 4),
            point_id=str(best.id),
        )
        asyncio.create_task(self._record_hit(best.id))  # noqa: RUF006 - best-effort, fire-and-forget
        response.cache_status = CacheStatus.SEMANTIC_HIT
        return response

    async def set(self, request: ChatRequest, response: ChatResponse, *, tenant_id: str) -> None:
        try:
            await asyncio.wait_for(
                self._set_impl(request, response, tenant_id), timeout=self._write_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - write-back is best-effort
            logger.warning(
                "semantic_cache_set_failed", error=str(exc), error_type=type(exc).__name__
            )

    async def _set_impl(self, request: ChatRequest, response: ChatResponse, tenant_id: str) -> None:
        await self.ensure_collection()
        prompt = normalize_prompt(request.canonical_prompt())
        vector = await self._embeddings.embed(prompt)

        payload = {
            "tenant_id": tenant_id,
            "model_family": request.model,
            "params_hash": compute_params_hash(request),
            "prompt_text": prompt[:MAX_STORED_PROMPT_CHARS],
            "response": response.model_dump(mode="json"),
            "created_at": datetime.now(UTC).isoformat(),
            "hit_count": 0,
        }
        await self._qdrant.upsert(
            collection_name=self._collection,
            points=[qmodels.PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload)],
        )

    async def _record_hit(self, point_id) -> None:
        try:
            await self._qdrant.set_payload(
                collection_name=self._collection,
                payload={"last_hit_at": datetime.now(UTC).isoformat()},
                points=[point_id],
            )
        except Exception as exc:  # noqa: BLE001 - popularity tracking is best-effort
            logger.debug("semantic_cache_hit_tracking_failed", error=str(exc))

    def _build_filter(self, request: ChatRequest, tenant_id: str) -> qmodels.Filter:
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="tenant_id", match=qmodels.MatchValue(value=tenant_id)),
                qmodels.FieldCondition(
                    key="model_family", match=qmodels.MatchValue(value=request.model)
                ),
                qmodels.FieldCondition(
                    key="params_hash",
                    match=qmodels.MatchValue(value=compute_params_hash(request)),
                ),
            ]
        )
