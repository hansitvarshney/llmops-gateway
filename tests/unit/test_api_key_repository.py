"""ApiKeyRepository tests against in-memory SQLite."""

import uuid
from datetime import UTC, datetime

from llmops_gateway.persistence.models.api_key import ApiKeyModel
from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.persistence.repositories.api_key_repository import ApiKeyRepository


async def _seed_tenant_and_key(
    sqlite_database,
    *,
    key_hash: str,
    scopes: list[str] | None = None,
    tenant_status: str = "active",
    revoked: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    api_key_id = uuid.uuid4()
    async with sqlite_database.session() as session:
        session.add(
            TenantModel(
                id=tenant_id,
                name="Tenant",
                slug=f"tenant-{tenant_id.hex[:8]}",
                status=tenant_status,
            )
        )
        session.add(
            ApiKeyModel(
                id=api_key_id,
                tenant_id=tenant_id,
                key_hash=key_hash,
                name="test-key",
                scopes=scopes or ["chat:write"],
                revoked_at=datetime.now(UTC) if revoked else None,
            )
        )
    return tenant_id, api_key_id


async def test_get_active_by_key_hash_returns_record(sqlite_database) -> None:
    key_hash = "abc123"
    tenant_id, api_key_id = await _seed_tenant_and_key(sqlite_database, key_hash=key_hash)

    async with sqlite_database.session() as session:
        record = await ApiKeyRepository(session).get_active_by_key_hash(key_hash)

    assert record is not None
    assert record.id == api_key_id
    assert record.tenant_id == tenant_id
    assert record.scopes == ["chat:write"]
    assert record.tenant_status == "active"


async def test_get_active_by_key_hash_ignores_revoked(sqlite_database) -> None:
    key_hash = "revoked-hash"
    await _seed_tenant_and_key(sqlite_database, key_hash=key_hash, revoked=True)

    async with sqlite_database.session() as session:
        record = await ApiKeyRepository(session).get_active_by_key_hash(key_hash)

    assert record is None


async def test_create_persists_api_key(sqlite_database) -> None:
    tenant_id = uuid.uuid4()
    async with sqlite_database.session() as session:
        session.add(
            TenantModel(id=tenant_id, name="Tenant", slug=f"tenant-{tenant_id.hex[:8]}")
        )
        created = await ApiKeyRepository(session).create(
            tenant_id=tenant_id,
            key_hash="new-hash",
            name="created-key",
            scopes=["*"],
        )

    async with sqlite_database.session() as session:
        found = await ApiKeyRepository(session).get_active_by_key_hash("new-hash")

    assert found is not None
    assert found.id == created.id
    assert found.scopes == ["*"]
