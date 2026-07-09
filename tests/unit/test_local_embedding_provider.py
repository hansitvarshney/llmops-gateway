"""Fast unit tests for LocalEmbeddingProvider using a monkeypatched fake
model — no real sentence-transformers/torch load. See
tests/integration/test_local_embedding_provider_integration.py for a test
against the real model."""

import asyncio

import numpy as np

from llmops_gateway.embeddings.local_provider import LocalEmbeddingProvider


class _FakeSentenceTransformerModel:
    def __init__(self, dimension: int = 8) -> None:
        self.dimension = dimension
        self.encode_calls: list[object] = []

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts, normalize_embeddings: bool = True):
        self.encode_calls.append(texts)
        if isinstance(texts, str):
            return np.ones(self.dimension)
        return np.ones((len(texts), self.dimension))


def _provider_with_fake_model(
    dimension: int = 8,
) -> tuple[LocalEmbeddingProvider, _FakeSentenceTransformerModel]:
    provider = LocalEmbeddingProvider(model_name="fake-model")
    fake_model = _FakeSentenceTransformerModel(dimension)
    provider._load_model = lambda: fake_model  # type: ignore[method-assign]
    return provider, fake_model


async def test_warm_up_loads_model_once_and_updates_dimension() -> None:
    provider, fake_model = _provider_with_fake_model(dimension=16)
    assert provider.dimension == 384  # default fallback before load

    await provider.warm_up()
    assert provider.dimension == 16
    assert provider._model is fake_model

    await provider.warm_up()  # idempotent — must not reload


async def test_embed_returns_vector_of_correct_dimension() -> None:
    provider, _ = _provider_with_fake_model(dimension=8)
    vector = await provider.embed("hello world")
    assert len(vector) == 8
    assert isinstance(vector, list)


async def test_embed_batch_returns_one_vector_per_input() -> None:
    provider, _ = _provider_with_fake_model(dimension=4)
    vectors = await provider.embed_batch(["a", "b", "c"])
    assert len(vectors) == 3
    assert all(len(v) == 4 for v in vectors)


def test_model_id_reflects_configured_model_name() -> None:
    provider = LocalEmbeddingProvider(model_name="all-MiniLM-L6-v2")
    assert provider.model_id == "local-all-MiniLM-L6-v2"


async def test_concurrent_embed_calls_only_load_model_once() -> None:
    provider, _ = _provider_with_fake_model(dimension=4)
    load_calls: list[int] = []
    original_load = provider._load_model

    def _tracked_load():
        load_calls.append(1)
        return original_load()

    provider._load_model = _tracked_load  # type: ignore[method-assign]
    await asyncio.gather(*[provider.embed("hi") for _ in range(5)])
    assert len(load_calls) == 1
