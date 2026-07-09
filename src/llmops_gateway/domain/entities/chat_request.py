"""Canonical, provider-agnostic representation of an inbound chat request.

Every provider adapter (OpenAI, Anthropic, ...) translates to/from this
shape, so the rest of the gateway (caching, routing, cost calc) never has to
know about provider-specific wire formats.
"""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    role: Role
    content: str


class ChatRequest(BaseModel):
    model: str = Field(..., description="Requested model, e.g. 'gpt-4o'.")
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: int | None = None
    top_p: float = 1.0
    stream: bool = False
    stop: list[str] | None = None

    # Gateway-specific extensions (ignored by upstream providers)
    cache_bypass: bool = Field(
        default=False, description="If true, skip both cache layers for this request."
    )
    provider_override: str | None = Field(
        default=None, description="Force a specific provider instead of the fallback chain."
    )

    def canonical_prompt(self) -> str:
        """Deterministic text representation used for cache-key hashing and embedding."""
        return "\n".join(f"{m.role}:{m.content}" for m in self.messages)

    def params_fingerprint(self) -> str:
        """Parameters that must match for a cache hit to be valid (excludes prompt text)."""
        return f"{self.model}|{self.temperature}|{self.max_tokens}|{self.top_p}|{self.stop}"
