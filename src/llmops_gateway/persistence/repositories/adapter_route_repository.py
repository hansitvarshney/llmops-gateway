"""CRUD + request-path lookup for adapter_routes."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.persistence.models.adapter_route import AdapterRouteModel


class AdapterRouteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(
        self,
        *,
        tenant_id: uuid.UUID,
        model_alias: str,
        stage: str = "Production",
    ) -> AdapterRouteModel | None:
        stmt = (
            select(AdapterRouteModel)
            .where(
                AdapterRouteModel.tenant_id == tenant_id,
                AdapterRouteModel.model_alias == model_alias,
                AdapterRouteModel.stage == stage,
                AdapterRouteModel.enabled.is_(True),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def resolve_with_canary(
        self,
        *,
        tenant_id: uuid.UUID,
        model_alias: str,
        routing_key: str,
        preferred_stage: str | None = None,
    ) -> AdapterRouteModel | None:
        """Pick Production vs Staging using Staging.canary_percent sticky hash.

        If ``preferred_stage`` is set (client override), honor that when present.
        Otherwise: hash(routing_key) % 100 < staging.canary_percent → Staging,
        else Production (fall back to whichever exists).
        """
        if preferred_stage:
            return await self.get_active(
                tenant_id=tenant_id, model_alias=model_alias, stage=preferred_stage
            )

        production = await self.get_active(
            tenant_id=tenant_id, model_alias=model_alias, stage="Production"
        )
        staging = await self.get_active(
            tenant_id=tenant_id, model_alias=model_alias, stage="Staging"
        )
        if staging is not None and int(staging.canary_percent or 0) > 0:
            bucket = int(hashlib.sha256(routing_key.encode("utf-8")).hexdigest()[:8], 16) % 100
            if bucket < int(staging.canary_percent):
                return staging
            return production or staging
        return production or staging

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[AdapterRouteModel]:
        stmt = (
            select(AdapterRouteModel)
            .where(AdapterRouteModel.tenant_id == tenant_id)
            .order_by(AdapterRouteModel.model_alias, AdapterRouteModel.stage)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        model_alias: str,
        base_model: str,
        adapter_id: str,
        stage: str = "Production",
        enabled: bool = True,
        canary_percent: int = 0,
    ) -> AdapterRouteModel:
        canary_percent = max(0, min(100, int(canary_percent)))
        existing = await self.get_by_unique(
            tenant_id=tenant_id, model_alias=model_alias, stage=stage
        )
        if existing is not None:
            existing.base_model = base_model
            existing.adapter_id = adapter_id
            existing.enabled = enabled
            existing.canary_percent = canary_percent
            await self._session.flush()
            return existing

        row = AdapterRouteModel(
            tenant_id=tenant_id,
            model_alias=model_alias,
            base_model=base_model,
            adapter_id=adapter_id,
            stage=stage,
            enabled=enabled,
            canary_percent=canary_percent,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_by_unique(
        self,
        *,
        tenant_id: uuid.UUID,
        model_alias: str,
        stage: str,
    ) -> AdapterRouteModel | None:
        stmt = (
            select(AdapterRouteModel)
            .where(
                AdapterRouteModel.tenant_id == tenant_id,
                AdapterRouteModel.model_alias == model_alias,
                AdapterRouteModel.stage == stage,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def disable(
        self,
        *,
        tenant_id: uuid.UUID,
        model_alias: str,
        stage: str,
    ) -> AdapterRouteModel | None:
        row = await self.get_by_unique(
            tenant_id=tenant_id, model_alias=model_alias, stage=stage
        )
        if row is None:
            return None
        row.enabled = False
        await self._session.flush()
        return row
