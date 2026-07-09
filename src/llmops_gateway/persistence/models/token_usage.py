import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, UUIDPrimaryKeyMixin


class TokenUsageModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "token_usage"

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("requests.id"), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    total_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    pricing_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("model_pricing.id"), nullable=True
    )
