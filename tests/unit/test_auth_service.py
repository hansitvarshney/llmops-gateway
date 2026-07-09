"""AuthService tests with SQLite + fakeredis."""

import uuid

import fakeredis.aioredis
import pytest

from llmops_gateway.persistence.models.api_key import ApiKeyModel
from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.security.api_keys import generate_api_key, hash_api_key
from llmops_gateway.services.auth_service import AuthService

PEPPER = "test-pepper"


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


async def _seed_key(sqlite_database, *, raw_key: str, scopes: list[str] | None = None) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    api_key_id = uuid.uuid4()
    key_hash = hash_api_key(raw_key, pepper=PEPPER)
    async with sqlite_database.session() as session:
        session.add(
            TenantModel(
                id=tenant_id,
                name="Tenant",
                slug=f"tenant-{tenant_id.hex[:8]}",
                status="active",
            )
        )
        session.add(
            ApiKeyModel(
                id=api_key_id,
                tenant_id=tenant_id,
                key_hash=key_hash,
                name="auth-test",
                scopes=scopes or ["chat:write"],
            )
        )
    return tenant_id


async def test_authenticate_returns_principal_for_valid_key(sqlite_database, fake_redis) -> None:
    raw_key = "llmops_valid_test_key"
    tenant_id = await _seed_key(sqlite_database, raw_key=raw_key)
    service = AuthService(sqlite_database, fake_redis, pepper=PEPPER, cache_ttl_seconds=60)

    principal = await service.authenticate(raw_key)

    assert principal is not None
    assert principal.tenant_id == str(tenant_id)
    assert principal.tenant_status == "active"
    assert "chat:write" in principal.scopes


async def test_authenticate_returns_none_for_invalid_key(sqlite_database, fake_redis) -> None:
    service = AuthService(sqlite_database, fake_redis, pepper=PEPPER, cache_ttl_seconds=60)
    assert await service.authenticate("llmops_unknown_key") is None
    assert await service.authenticate("bad-format") is None


async def test_authenticate_uses_redis_cache(sqlite_database, fake_redis) -> None:
    raw_key = "llmops_cached_key"
    await _seed_key(sqlite_database, raw_key=raw_key)
    service = AuthService(sqlite_database, fake_redis, pepper=PEPPER, cache_ttl_seconds=60)

    first = await service.authenticate(raw_key)
    second = await service.authenticate(raw_key)

    assert first is not None and second is not None
    assert first.tenant_id == second.tenant_id
    assert await fake_redis.exists(f"auth:v1:{hash_api_key(raw_key, pepper=PEPPER)}")


async def test_create_api_key_persists_record(sqlite_database, fake_redis) -> None:
    tenant_id = uuid.uuid4()
    async with sqlite_database.session() as session:
        session.add(
            TenantModel(id=tenant_id, name="Tenant", slug=f"tenant-{tenant_id.hex[:8]}")
        )

    service = AuthService(sqlite_database, fake_redis, pepper=PEPPER, cache_ttl_seconds=60)
    raw, digest = generate_api_key(pepper=PEPPER)
    api_key_id = await service.create_api_key(
        tenant_id=tenant_id,
        key_hash=digest,
        name="created",
        scopes=["*"],
    )

    principal = await service.authenticate(raw)
    assert principal is not None
    assert principal.api_key_id == str(api_key_id)
