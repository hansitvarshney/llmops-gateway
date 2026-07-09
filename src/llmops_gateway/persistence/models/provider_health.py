from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, UUIDPrimaryKeyMixin


class ProviderHealthModel(Base, UUIDPrimaryKeyMixin):
    """Rolling error/latency stats per (provider, model), feeding the
    circuit breaker and admin observability dashboards."""

    __tablename__ = "provider_health"

    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    circuit_state: Mapped[str] = mapped_column(String(16), default="closed")
