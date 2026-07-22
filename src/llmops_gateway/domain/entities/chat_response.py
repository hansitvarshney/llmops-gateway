"""Canonical, provider-agnostic representation of a chat completion response."""

from datetime import datetime

from pydantic import BaseModel

from llmops_gateway.domain.entities.chat_request import ChatMessage
from llmops_gateway.domain.value_objects.cache_status import CacheStatus


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ChatResponse(BaseModel):
    id: str
    model: str
    provider: str
    message: ChatMessage
    usage: TokenUsage
    cost_usd: float
    cache_status: CacheStatus = CacheStatus.MISS
    trace_id: str
    created_at: datetime
    latency_ms: float
    adapter_id: str | None = None
    model_alias: str | None = None
    adapter_stage: str | None = None
