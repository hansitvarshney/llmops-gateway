"""Data-access layer for `model_pricing`, consumed by CostService.

Reads are cached in Redis by CostService with a short TTL (pricing changes
infrequently) so a Postgres round-trip only happens on a cache miss.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.persistence.models.model_pricing import ModelPricingModel


class PricingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_price(
        self, provider: str, model: str, at: datetime
    ) -> ModelPricingModel | None:
        """The pricing row for (provider, model) whose effective window
        covers `at`, preferring the most recently-effective row if more than
        one somehow overlaps."""
        stmt = (
            select(ModelPricingModel)
            .where(
                ModelPricingModel.provider == provider,
                ModelPricingModel.model_name == model,
                ModelPricingModel.effective_from <= at,
                or_(
                    ModelPricingModel.effective_to.is_(None),
                    ModelPricingModel.effective_to > at,
                ),
            )
            .order_by(ModelPricingModel.effective_from.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self, at: datetime | None = None) -> list[ModelPricingModel]:
        at = at or datetime.now(UTC)
        stmt = (
            select(ModelPricingModel)
            .where(
                ModelPricingModel.effective_from <= at,
                or_(
                    ModelPricingModel.effective_to.is_(None),
                    ModelPricingModel.effective_to > at,
                ),
            )
            .order_by(
                ModelPricingModel.provider,
                ModelPricingModel.model_name,
                ModelPricingModel.effective_from.desc(),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        provider: str,
        model_name: str,
        input_price_per_1k: Decimal,
        output_price_per_1k: Decimal,
        currency: str = "USD",
        effective_from: datetime,
        effective_to: datetime | None = None,
    ) -> ModelPricingModel:
        row = ModelPricingModel(
            provider=provider,
            model_name=model_name,
            input_price_per_1k=input_price_per_1k,
            output_price_per_1k=output_price_per_1k,
            currency=currency,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        self._session.add(row)
        await self._session.flush()
        return row
