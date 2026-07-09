"""Port for a single cache layer (Redis exact-match or Qdrant semantic).

Each layer receives the full `ChatRequest` (not a pre-computed key) because
what "identity" means differs per layer: Redis hashes the exact normalized
prompt + parameters, while Qdrant embeds the prompt text and filters on
model/params/tenant separately from the similarity search itself.
`CacheService` composes two `CacheStore` implementations rather than hard
depending on Redis/Qdrant clients directly, which keeps it unit-testable and
makes it possible to swap either layer independently.
"""

from abc import ABC, abstractmethod

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse


class CacheStore(ABC):
    @abstractmethod
    async def get(self, request: ChatRequest, *, tenant_id: str) -> ChatResponse | None:
        """Look up a cached response. Must enforce an internal timeout and
        fail closed (return None) rather than raise, so a degraded cache
        backend never breaks the request path."""
        raise NotImplementedError

    @abstractmethod
    async def set(self, request: ChatRequest, response: ChatResponse, *, tenant_id: str) -> None:
        """Write-back a fresh response. Called from the background
        write-back path, never on the synchronous request path. Must also
        fail closed (log + swallow) rather than raise."""
        raise NotImplementedError
