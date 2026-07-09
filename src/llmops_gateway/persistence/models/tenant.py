from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class TenantModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    budget_monthly_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
