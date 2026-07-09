import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, UUIDPrimaryKeyMixin


class RequestSpanModel(Base, UUIDPrimaryKeyMixin):
    """Step-by-step latency breakdown for a single request (cache_lookup,
    upstream_call, cost_calculation, ...)."""

    __tablename__ = "request_spans"

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("requests.id"), index=True)
    span_name: Mapped[str] = mapped_column(String(128))
    parent_span_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    span_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
