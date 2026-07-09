"""Data-access layer for `api_keys`, joined with tenant status for auth."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.persistence.models.api_key import ApiKeyModel
from llmops_gateway.persistence.models.tenant import TenantModel


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    id: uuid.UUID
    tenant_id: uuid.UUID
    scopes: list[str]
    tenant_status: str
    revoked_at: datetime | None


class ApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_by_key_hash(self, key_hash: str) -> ApiKeyRecord | None:
        stmt = (
            select(ApiKeyModel, TenantModel.status)
            .join(TenantModel, ApiKeyModel.tenant_id == TenantModel.id)
            .where(
                ApiKeyModel.key_hash == key_hash,
                ApiKeyModel.revoked_at.is_(None),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None

        api_key, tenant_status = row
        return ApiKeyRecord(
            id=api_key.id,
            tenant_id=api_key.tenant_id,
            scopes=list(api_key.scopes or []),
            tenant_status=tenant_status,
            revoked_at=api_key.revoked_at,
        )

    async def touch_last_used(self, api_key_id: uuid.UUID) -> None:
        await self._session.execute(
            update(ApiKeyModel)
            .where(ApiKeyModel.id == api_key_id)
            .values(last_used_at=datetime.now(UTC))
        )

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        key_hash: str,
        name: str,
        scopes: list[str],
    ) -> ApiKeyModel:
        record = ApiKeyModel(
            tenant_id=tenant_id,
            key_hash=key_hash,
            name=name,
            scopes=scopes,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_by_tenant(self, tenant_id: uuid.UUID) -> list[ApiKeyModel]:
        stmt = (
            select(ApiKeyModel)
            .where(ApiKeyModel.tenant_id == tenant_id)
            .order_by(ApiKeyModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, api_key_id: uuid.UUID) -> ApiKeyModel | None:
        result = await self._session.execute(
            select(ApiKeyModel).where(ApiKeyModel.id == api_key_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def revoke(self, api_key_id: uuid.UUID) -> bool:
        record = await self.get_by_id(api_key_id)
        if record is None or record.revoked_at is not None:
            return False
        record.revoked_at = datetime.now(UTC)
        await self._session.flush()
        return True
