"""Data-access layer for `tenants`."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.persistence.models.tenant import TenantModel


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[TenantModel]:
        result = await self._session.execute(select(TenantModel).order_by(TenantModel.created_at))
        return list(result.scalars().all())

    async def get_by_id(self, tenant_id: uuid.UUID) -> TenantModel | None:
        result = await self._session.execute(
            select(TenantModel).where(TenantModel.id == tenant_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, *, name: str, slug: str, status: str = "active") -> TenantModel:
        tenant = TenantModel(name=name, slug=slug, status=status)
        self._session.add(tenant)
        await self._session.flush()
        return tenant
