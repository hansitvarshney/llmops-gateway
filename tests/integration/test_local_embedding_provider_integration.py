"""Loads the real sentence-transformers model — slow (multi-second) and
requires network access on first run to download weights. Excluded from the
default test run (see `addopts = "-m 'not integration'"` in pyproject.toml);
run explicitly with `pytest -m integration`.
"""

import pytest

from llmops_gateway.embeddings.local_provider import LocalEmbeddingProvider

pytestmark = pytest.mark.integration


async def test_real_model_warm_up_and_embed() -> None:
    provider = LocalEmbeddingProvider(model_name="all-MiniLM-L6-v2")
    await provider.warm_up()
    assert provider.dimension == 384

    vector = await provider.embed("what is the capital of france")
    assert len(vector) == 384
    assert any(component != 0.0 for component in vector)
