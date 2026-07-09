"""Shared async Redis client factory.

A single connection-pooled client is created in main.py's lifespan and
reused by the exact cache, rate limiter, and request-coalescing lock —
never opened per-request.
"""

from redis.asyncio import ConnectionPool, Redis

from llmops_gateway.config.settings import Settings


def create_redis_client(settings: Settings) -> Redis:
    pool = ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
    )
    return Redis(connection_pool=pool)
