"""Per-tenant rate limiting backed by a Redis token-bucket."""

import time

import structlog
from redis.asyncio import Redis
from redis.exceptions import WatchError

logger = structlog.get_logger(__name__)


class RateLimitExceededError(Exception):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("Rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class RateLimitService:
    _RATE_LIMIT_PREFIX = "ratelimit:tenant:"

    def __init__(
        self,
        redis_client: Redis,
        *,
        default_limit_per_minute: int,
        enabled: bool = True,
        fail_open: bool = False,
    ) -> None:
        self._redis = redis_client
        self._default_limit_per_minute = default_limit_per_minute
        self._enabled = enabled
        self._fail_open = fail_open

    async def check_and_increment(
        self,
        tenant_id: str,
        *,
        limit_per_minute: int | None = None,
        cost: float = 1.0,
    ) -> None:
        """Raises RateLimitExceededError if the tenant is over budget."""
        if not self._enabled:
            return

        limit = limit_per_minute or self._default_limit_per_minute
        if limit <= 0:
            return

        key = f"{self._RATE_LIMIT_PREFIX}{tenant_id}"
        capacity = float(limit)
        refill_rate = limit / 60.0
        now_ms = int(time.time() * 1000)

        try:
            allowed, retry_after = await self._consume_token(
                key=key,
                capacity=capacity,
                refill_rate=refill_rate,
                now_ms=now_ms,
                cost=cost,
            )
        except Exception as exc:
            if self._fail_open:
                logger.warning(
                    "rate_limit_redis_error_fail_open",
                    tenant_id=tenant_id,
                    error=str(exc),
                )
                return
            logger.error("rate_limit_redis_error", tenant_id=tenant_id, error=str(exc))
            raise

        if not allowed:
            raise RateLimitExceededError(max(retry_after, 0.001))

    async def _consume_token(
        self,
        *,
        key: str,
        capacity: float,
        refill_rate: float,
        now_ms: int,
        cost: float,
    ) -> tuple[bool, float]:
        """Refill a token bucket stored in Redis and consume `cost` if allowed."""
        for _ in range(5):
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                raw = await self._redis.hmget(key, "tokens", "last_refill_ms")
                tokens = float(raw[0]) if raw[0] is not None else capacity
                last_refill_ms = int(raw[1]) if raw[1] is not None else now_ms

                elapsed_sec = max(0.0, (now_ms - last_refill_ms) / 1000.0)
                tokens = min(capacity, tokens + elapsed_sec * refill_rate)

                if tokens < cost:
                    await pipe.unwatch()
                    retry_after = (cost - tokens) / refill_rate
                    await self._persist_bucket(key, tokens, now_ms, capacity, refill_rate)
                    return False, retry_after

                new_tokens = tokens - cost
                ttl_ms = max(int((capacity / refill_rate) * 2000), 1000)
                pipe.multi()
                pipe.hset(
                    key,
                    mapping={"tokens": str(new_tokens), "last_refill_ms": str(now_ms)},
                )
                pipe.pexpire(key, ttl_ms)
                try:
                    await pipe.execute()
                except WatchError:
                    continue
                return True, 0.0

        # Contention exhausted — treat as limited to avoid unbounded retries.
        return False, 1.0 / refill_rate

    async def _persist_bucket(
        self,
        key: str,
        tokens: float,
        now_ms: int,
        capacity: float,
        refill_rate: float,
    ) -> None:
        ttl_ms = max(int((capacity / refill_rate) * 2000), 1000)
        await self._redis.hset(
            key,
            mapping={"tokens": str(tokens), "last_refill_ms": str(now_ms)},
        )
        await self._redis.pexpire(key, ttl_ms)
