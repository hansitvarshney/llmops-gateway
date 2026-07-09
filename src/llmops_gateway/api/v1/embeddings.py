"""Passthrough embeddings endpoint (for clients that want raw embeddings,
distinct from the internal semantic-cache embedding pipeline).

TODO(provider_adapters): proxy to the configured provider's embeddings API.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["embeddings"])


@router.post("/embeddings")
async def create_embedding() -> dict:
    raise NotImplementedError
