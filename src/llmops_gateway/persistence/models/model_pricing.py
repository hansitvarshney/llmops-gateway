from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ModelPricingModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Versioned pricing so historical cost calculations stay correct even
    after a provider changes its rates (see CostService)."""

    __tablename__ = "model_pricing"

    provider: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(128), index=True)
    input_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    output_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
