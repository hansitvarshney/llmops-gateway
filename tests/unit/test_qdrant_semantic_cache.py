"""QdrantSemanticCache tests against a real in-process Qdrant instance
(`AsyncQdrantClient(location=":memory:")`) — genuinely exercises payload
filtering and cosine-similarity scoring without needing Docker/a live
server. A deterministic fake EmbeddingProvider maps specific prompt texts to
hand-picked vectors so each test controls similarity exactly."""

from datetime import UTC, datetime

from qdrant_client import AsyncQdrantClient

from llmops_gateway.caching.qdrant_semantic_cache import QdrantSemanticCache
from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.interfaces.embedding_provider import EmbeddingProvider
from llmops_gateway.domain.value_objects.cache_status import CacheStatus

DIMENSION = 4


class _DeterministicEmbeddingProvider(EmbeddingProvider):
    """Maps *prompt text* (not the raw canonical-prompt string, which is
    prefixed with the message role by `ChatRequest.canonical_prompt()`) to
    hand-picked vectors, so tests can control cosine similarity exactly."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        # Keyed by the raw prompt text; embed() strips the "role:" prefix
        # that canonical_prompt()/normalize_prompt() leave in place, so
        # tests don't need to know about that implementation detail.
        self._vectors = vectors

    @property
    def model_id(self) -> str:
        return "deterministic-test-model"

    @property
    def dimension(self) -> int:
        return DIMENSION

    async def embed(self, text: str) -> list[float]:
        _, _, prompt_text = text.partition(":")
        return self._vectors.get(prompt_text, [0.0] * DIMENSION)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


class _BrokenEmbeddingProvider(_DeterministicEmbeddingProvider):
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding backend is down")


def _response(content: str = "cached answer") -> ChatResponse:
    return ChatResponse(
        id="1",
        model="gpt-4o",
        provider="openai",
        message=ChatMessage(role="assistant", content=content),
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.0,
        cache_status=CacheStatus.MISS,
        trace_id="t1",
        created_at=datetime.now(UTC),
        latency_ms=1.0,
    )


def _request(prompt: str = "what is the capital of france", **overrides) -> ChatRequest:
    defaults = {"model": "gpt-4o", "messages": [ChatMessage(role="user", content=prompt)]}
    defaults.update(overrides)
    return ChatRequest(**defaults)


def _make_cache(vectors: dict[str, list[float]], threshold: float = 0.95) -> QdrantSemanticCache:
    client = AsyncQdrantClient(location=":memory:")
    embeddings = _DeterministicEmbeddingProvider(vectors)
    return QdrantSemanticCache(client, embeddings, threshold, search_timeout_ms=2000)


async def test_miss_on_empty_collection() -> None:
    cache = _make_cache({"what is the capital of france": [1.0, 0.0, 0.0, 0.0]})
    result = await cache.get(_request(), tenant_id="t1")
    assert result is None


async def test_near_duplicate_prompt_is_a_hit_above_threshold() -> None:
    original = "what is the capital of france"
    near_duplicate = "what's the capital of france?"
    vectors = {
        original: [1.0, 0.0, 0.0, 0.0],
        near_duplicate: [0.999, 0.001, 0.0, 0.0],  # cosine similarity ~0.9999 > 0.95
    }
    cache = _make_cache(vectors, threshold=0.95)

    await cache.set(_request(original), _response("Paris"), tenant_id="t1")
    hit = await cache.get(_request(near_duplicate), tenant_id="t1")

    assert hit is not None
    assert hit.message.content == "Paris"
    assert hit.cache_status == CacheStatus.SEMANTIC_HIT


async def test_dissimilar_prompt_is_a_miss_below_threshold() -> None:
    original = "what is the capital of france"
    unrelated = "write me a haiku about the ocean"
    vectors = {
        original: [1.0, 0.0, 0.0, 0.0],
        unrelated: [0.0, 1.0, 0.0, 0.0],  # orthogonal -> cosine similarity 0
    }
    cache = _make_cache(vectors, threshold=0.95)

    await cache.set(_request(original), _response("Paris"), tenant_id="t1")
    hit = await cache.get(_request(unrelated), tenant_id="t1")
    assert hit is None


async def test_hit_is_scoped_to_tenant() -> None:
    prompt = "what is the capital of france"
    cache = _make_cache({prompt: [1.0, 0.0, 0.0, 0.0]})

    await cache.set(_request(prompt), _response("Paris"), tenant_id="tenant-a")
    assert await cache.get(_request(prompt), tenant_id="tenant-b") is None
    assert await cache.get(_request(prompt), tenant_id="tenant-a") is not None


async def test_hit_is_scoped_to_model_and_params() -> None:
    prompt = "what is the capital of france"
    cache = _make_cache({prompt: [1.0, 0.0, 0.0, 0.0]})

    await cache.set(_request(prompt, model="gpt-4o"), _response("Paris"), tenant_id="t1")

    different_model_hit = await cache.get(_request(prompt, model="gpt-4o-mini"), tenant_id="t1")
    different_params_hit = await cache.get(_request(prompt, temperature=0.1), tenant_id="t1")

    assert different_model_hit is None
    assert different_params_hit is None


async def test_get_fails_closed_when_embedding_raises() -> None:
    client = AsyncQdrantClient(location=":memory:")
    cache = QdrantSemanticCache(client, _BrokenEmbeddingProvider({}), 0.95, search_timeout_ms=2000)

    result = await cache.get(_request(), tenant_id="t1")
    assert result is None  # never raises


async def test_set_fails_silently_when_embedding_raises() -> None:
    client = AsyncQdrantClient(location=":memory:")
    cache = QdrantSemanticCache(client, _BrokenEmbeddingProvider({}), 0.95, search_timeout_ms=2000)

    await cache.set(_request(), _response(), tenant_id="t1")  # must not raise
