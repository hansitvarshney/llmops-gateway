"""Admin repository tests."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.persistence.repositories.api_key_repository import ApiKeyRepository
from llmops_gateway.persistence.repositories.pricing_repository import PricingRepository
from llmops_gateway.persistence.repositories.tenant_repository import TenantRepository


async def test_tenant_repository_create_and_list(sqlite_database) -> None:
    async with sqlite_database.session() as session:
        created = await TenantRepository(session).create(name="Acme", slug="acme")
        tenants = await TenantRepository(session).list_all()

    assert any(t.id == created.id for t in tenants)
    assert created.slug == "acme"


async def test_api_key_revoke(sqlite_database) -> None:
    tenant_id = uuid.uuid4()
    async with sqlite_database.session() as session:
        session.add(TenantModel(id=tenant_id, name="T", slug="t-revoke"))
        repo = ApiKeyRepository(session)
        key = await repo.create(
            tenant_id=tenant_id,
            key_hash="hash-revoke",
            name="k1",
            scopes=["*"],
        )

    async with sqlite_database.session() as session:
        repo = ApiKeyRepository(session)
        assert await repo.revoke(key.id) is True
        assert await repo.get_active_by_key_hash("hash-revoke") is None


async def test_pricing_repository_create_and_list(sqlite_database) -> None:
    now = datetime.now(UTC)
    async with sqlite_database.session() as session:
        await PricingRepository(session).create(
            provider="openai",
            model_name="gpt-test",
            input_price_per_1k=Decimal("0.001"),
            output_price_per_1k=Decimal("0.002"),
            effective_from=now,
        )
        rows = await PricingRepository(session).list_active(at=now)

    assert any(r.model_name == "gpt-test" for r in rows)
