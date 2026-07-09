"""Coordinates the dual-layer cache lookup described in the architecture plan.

Order of operations for `lookup()`:
  1. Layer 1 (Redis exact match) — fast path, checked first.
  2. Layer 2 (Qdrant semantic match) — only on Layer-1 miss, unless
     `request.cache_bypass` is set. A semantic hit is backfilled into
     Layer 1 immediately so the *next* identical request is an O(1) exact
     hit rather than paying the embedding + vector-search cost again.

Also owns request-coalescing for the non-streaming path: concurrent
identical in-flight requests (same exact-cache key) acquire a short-TTL
Redis lock before calling the upstream provider; the caller that loses the
race polls the exact cache briefly for the winner's result instead of also
calling the provider — the "thundering herd" mitigation from the plan.
Coalescing is best-effort and fails open (proceeds to call the provider
directly) if Redis itself is unavailable or the wait times out, so it can
never turn into an availability problem of its own. Streaming responses are
not coalesced — see GatewayService for why.
"""

import asyncio
import time

import structlog
from redis.exceptions import RedisError

from llmops_gateway.caching.hashing import exact_cache_key
from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse
from llmops_gateway.domain.interfaces.cache_store import CacheStore
from llmops_gateway.domain.value_objects.cache_status import CacheStatus

logger = structlog.get_logger(__name__)

DEFAULT_COALESCING_LOCK_TTL_SECONDS = 10.0
DEFAULT_COALESCING_WAIT_SECONDS = 2.0
DEFAULT_COALESCING_POLL_INTERVAL_SECONDS = 0.05


class CacheService:
    def __init__(
        self,
        exact_cache: CacheStore,
        semantic_cache: CacheStore,
        redis_client,
        coalescing_lock_ttl_seconds: float = DEFAULT_COALESCING_LOCK_TTL_SECONDS,
        coalescing_wait_seconds: float = DEFAULT_COALESCING_WAIT_SECONDS,
        coalescing_poll_interval_seconds: float = DEFAULT_COALESCING_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._exact_cache = exact_cache
        self._semantic_cache = semantic_cache
        self._redis = redis_client
        self._coalescing_lock_ttl_seconds = coalescing_lock_ttl_seconds
        self._coalescing_wait_seconds = coalescing_wait_seconds
        self._coalescing_poll_interval_seconds = coalescing_poll_interval_seconds

    async def lookup(
        self, request: ChatRequest, *, tenant_id: str
    ) -> tuple[ChatResponse | None, CacheStatus]:
        if request.cache_bypass:
            return None, CacheStatus.BYPASSED

        exact_hit = await self._exact_cache.get(request, tenant_id=tenant_id)
        if exact_hit is not None:
            return exact_hit, CacheStatus.EXACT_HIT

        semantic_hit = await self._semantic_cache.get(request, tenant_id=tenant_id)
        if semantic_hit is not None:
            # Fire-and-forget: don't let an L1 backfill failure delay the response.
            asyncio.create_task(self._exact_cache.set(request, semantic_hit, tenant_id=tenant_id))  # noqa: RUF006
            return semantic_hit, CacheStatus.SEMANTIC_HIT

        return None, CacheStatus.MISS

    async def backfill(
        self, request: ChatRequest, response: ChatResponse, *, tenant_id: str
    ) -> None:
        """Called after a fresh upstream response — writes through both
        cache layers so future identical/similar requests can be served
        from cache. Intended to be awaited from a fire-and-forget task, not
        the synchronous request path."""
        await asyncio.gather(
            self._exact_cache.set(request, response, tenant_id=tenant_id),
            self._semantic_cache.set(request, response, tenant_id=tenant_id),
            return_exceptions=True,
        )

    async def acquire_coalescing_lock(self, request: ChatRequest, *, tenant_id: str) -> bool:
        """Best-effort SETNX lock so concurrent identical cache-miss requests
        don't all hammer the upstream provider simultaneously.

        Returns True if this caller won the lock and should proceed to call
        the provider itself (and must call `release_coalescing_lock` when
        done). Returns False if another caller is already in flight — the
        caller should then use `wait_for_coalesced_result` instead of also
        calling the provider. Fails open (returns True) if Redis itself is
        unavailable, since the lock is a latency optimization, not a
        correctness requirement.
        """
        key = self._lock_key(request, tenant_id)
        try:
            acquired = await self._redis.set(
                key, "1", nx=True, ex=int(self._coalescing_lock_ttl_seconds)
            )
        except RedisError as exc:
            logger.warning("coalescing_lock_acquire_failed", error=str(exc))
            return True
        return bool(acquired)

    async def release_coalescing_lock(self, request: ChatRequest, *, tenant_id: str) -> None:
        key = self._lock_key(request, tenant_id)
        try:
            await self._redis.delete(key)
        except RedisError as exc:
            logger.warning("coalescing_lock_release_failed", error=str(exc))

    async def wait_for_coalesced_result(
        self, request: ChatRequest, *, tenant_id: str
    ) -> ChatResponse | None:
        """Polls the exact cache for the in-flight winner's result. Returns
        None (never raises) if it doesn't show up within the wait budget —
        the caller should then fall through and call the provider itself
        rather than blocking indefinitely on another request's success."""
        deadline = time.monotonic() + self._coalescing_wait_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(self._coalescing_poll_interval_seconds)
            hit = await self._exact_cache.get(request, tenant_id=tenant_id)
            if hit is not None:
                return hit
        return None

    @staticmethod
    def _lock_key(request: ChatRequest, tenant_id: str) -> str:
        return f"lock:{exact_cache_key(request)}:tenant:{tenant_id}"
