"""API-key authentication with Redis-backed principal caching."""

import asyncio
import uuid

import orjson
import structlog
from redis.asyncio import Redis

from llmops_gateway.domain.entities.auth_context import AuthenticatedPrincipal
from llmops_gateway.persistence.database import Database
from llmops_gateway.persistence.repositories.api_key_repository import ApiKeyRepository
from llmops_gateway.security.api_keys import hash_api_key, is_valid_api_key_format

logger = structlog.get_logger(__name__)

_AUTH_CACHE_PREFIX = "auth:v1:"


class AuthService:
    def __init__(
        self,
        database: Database,
        redis: Redis,
        *,
        pepper: str,
        cache_ttl_seconds: float,
    ) -> None:
        self._database = database
        self._redis = redis
        self._pepper = pepper
        self._cache_ttl_seconds = cache_ttl_seconds

    async def authenticate(self, raw_key: str) -> AuthenticatedPrincipal | None:
        if not is_valid_api_key_format(raw_key):
            return None

        key_hash = hash_api_key(raw_key, pepper=self._pepper)
        cached = await self._get_cached(key_hash)
        if cached is not None:
            return cached

        principal = await self._load_from_database(key_hash)
        if principal is None:
            return None

        await self._set_cached(key_hash, principal)
        asyncio.create_task(self._touch_last_used(principal.api_key_id))  # noqa: RUF006
        return principal

    async def create_api_key(
        self,
        *,
        tenant_id: uuid.UUID,
        key_hash: str,
        name: str,
        scopes: list[str],
    ) -> uuid.UUID:
        async with self._database.session() as session:
            repo = ApiKeyRepository(session)
            record = await repo.create(
                tenant_id=tenant_id,
                key_hash=key_hash,
                name=name,
                scopes=scopes,
            )
            return record.id

    async def invalidate_cache_by_hash(self, key_hash: str) -> None:
        await self._redis.delete(f"{_AUTH_CACHE_PREFIX}{key_hash}")

    async def revoke_api_key(self, api_key_id: uuid.UUID) -> bool:
        async with self._database.session() as session:
            repo = ApiKeyRepository(session)
            record = await repo.get_by_id(api_key_id)
            if record is None:
                return False
            revoked = await repo.revoke(api_key_id)
            if revoked:
                await self.invalidate_cache_by_hash(record.key_hash)
            return revoked

    def _cache_key(self, key_hash: str) -> str:
        return f"{_AUTH_CACHE_PREFIX}{key_hash}"

    async def _get_cached(self, key_hash: str) -> AuthenticatedPrincipal | None:
        try:
            payload = await self._redis.get(self._cache_key(key_hash))
        except Exception as exc:  # noqa: BLE001 - cache miss on Redis errors
            logger.warning("auth_cache_read_failed", error=str(exc))
            return None

        if payload is None:
            return None

        try:
            data = orjson.loads(payload)
            return AuthenticatedPrincipal(
                tenant_id=data["tenant_id"],
                api_key_id=data["api_key_id"],
                tenant_status=data["tenant_status"],
                scopes=frozenset(data["scopes"]),
                rate_limit_per_minute=data.get("rate_limit_per_minute"),
            )
        except (orjson.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("auth_cache_decode_failed", error=str(exc))
            await self._redis.delete(self._cache_key(key_hash))
            return None

    async def _set_cached(self, key_hash: str, principal: AuthenticatedPrincipal) -> None:
        payload = orjson.dumps(
            {
                "tenant_id": principal.tenant_id,
                "api_key_id": principal.api_key_id,
                "tenant_status": principal.tenant_status,
                "scopes": sorted(principal.scopes),
                "rate_limit_per_minute": principal.rate_limit_per_minute,
            }
        )
        try:
            await self._redis.set(
                self._cache_key(key_hash),
                payload,
                ex=int(self._cache_ttl_seconds),
            )
        except Exception as exc:  # noqa: BLE001 - auth still succeeds without cache
            logger.warning("auth_cache_write_failed", error=str(exc))

    async def _load_from_database(self, key_hash: str) -> AuthenticatedPrincipal | None:
        async with self._database.session() as session:
            repo = ApiKeyRepository(session)
            record = await repo.get_active_by_key_hash(key_hash)
            if record is None:
                return None

            return AuthenticatedPrincipal(
                tenant_id=str(record.tenant_id),
                api_key_id=str(record.id),
                tenant_status=record.tenant_status,
                scopes=frozenset(record.scopes),
            )

    async def _touch_last_used(self, api_key_id: str) -> None:
        try:
            async with self._database.session() as session:
                repo = ApiKeyRepository(session)
                await repo.touch_last_used(uuid.UUID(api_key_id))
        except Exception as exc:  # noqa: BLE001 - bookkeeping must not break auth
            logger.debug("auth_touch_last_used_failed", api_key_id=api_key_id, error=str(exc))
