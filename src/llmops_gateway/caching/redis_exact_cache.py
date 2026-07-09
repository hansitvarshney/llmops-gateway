"""Layer 1: Redis exact-match cache.

Implements the CacheStore port. Every call enforces a short internal
timeout and swallows Redis errors (fail closed to a cache MISS/no-op) so a
degraded Redis instance never adds latency or breaks the request path —
see the Redis circuit-breaker discussion in the architecture plan. This is
deliberately simpler than the LLM-provider resilience layer (no retry, no
circuit breaker): a single fast-failing attempt is the right trade-off for
a cache that's supposed to be a latency *optimization*, not a dependency.
"""

import asyncio

import structlog
from redis.exceptions import RedisError

from llmops_gateway.caching.hashing import exact_cache_key
from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.domain.interfaces.cache_store import CacheStore
from llmops_gateway.domain.value_objects.cache_status import CacheStatus

logger = structlog.get_logger(__name__)

DEFAULT_GET_TIMEOUT_SECONDS = 0.05
DEFAULT_SET_TIMEOUT_SECONDS = 0.2


class RedisExactCache(CacheStore):
    def __init__(
        self,
        redis_client,
        ttl_seconds: int,
        get_timeout_seconds: float = DEFAULT_GET_TIMEOUT_SECONDS,
        set_timeout_seconds: float = DEFAULT_SET_TIMEOUT_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._get_timeout_seconds = get_timeout_seconds
        self._set_timeout_seconds = set_timeout_seconds

    async def get(self, request: ChatRequest, *, tenant_id: str) -> ChatResponse | None:
        key = self._key(request, tenant_id)
        try:
            raw = await asyncio.wait_for(self._redis.get(key), timeout=self._get_timeout_seconds)
        except (TimeoutError, RedisError) as exc:
            logger.warning("redis_exact_cache_get_failed", error=str(exc))
            return None

        if raw is None:
            return None

        try:
            response = ChatResponse.model_validate_json(raw)
        except ValueError as exc:
            logger.warning("redis_exact_cache_corrupt_entry", key=key, error=str(exc))
            return None

        response.cache_status = CacheStatus.EXACT_HIT
        return response

    async def set(self, request: ChatRequest, response: ChatResponse, *, tenant_id: str) -> None:
        key = self._key(request, tenant_id)
        try:
            await asyncio.wait_for(
                self._redis.set(key, response.model_dump_json(), ex=self._ttl_seconds),
                timeout=self._set_timeout_seconds,
            )
        except (TimeoutError, RedisError) as exc:
            logger.warning("redis_exact_cache_set_failed", error=str(exc))

    @staticmethod
    def _key(request: ChatRequest, tenant_id: str) -> str:
        return f"{exact_cache_key(request)}:tenant:{tenant_id}"
