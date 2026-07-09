"""Port implemented by every upstream LLM adapter (OpenAI, Anthropic, ...).

`RoutingService` depends only on this interface, never on a concrete
provider, so adding a new upstream is a matter of implementing this ABC and
registering it in `providers.registry` — no changes to the gateway core.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage


class LLMProvider(ABC):
    """A single upstream LLM provider (e.g. OpenAI)."""

    name: str

    @abstractmethod
    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Non-streaming completion. Raises ProviderError subclasses on failure."""
        raise NotImplementedError

    @abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Streaming completion — yields raw text deltas as they arrive.

        Implementations must ensure the upstream connection is cancelled
        promptly if the consumer stops iterating (client disconnect).
        """
        raise NotImplementedError

    @abstractmethod
    def supports_model(self, model: str) -> bool:
        """Whether this provider can serve the given model name."""
        raise NotImplementedError

    @abstractmethod
    async def count_tokens(self, request: ChatRequest, completion_text: str) -> TokenUsage:
        """Best-available token accounting, used when a provider's streaming
        API doesn't return a final usage object."""
        raise NotImplementedError
