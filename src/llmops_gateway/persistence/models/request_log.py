import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, UUIDPrimaryKeyMixin


class RequestLogModel(Base, UUIDPrimaryKeyMixin):
    """The core audit log — one row per gateway request.

    High write-volume, append-only. In production this table should be
    partitioned monthly on `created_at` (via an Alembic migration using
    native Postgres declarative partitioning) with older partitions archived
    to cold storage (S3/Parquet) — see the "Postgres write amplification"
    mitigation in the architecture plan.
    """

    __tablename__ = "requests"

    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("tenants.id"), index=True)
    # Nullable until real API-key authentication is wired (middleware_security
    # phase) — every request today runs under the seeded default tenant with
    # no authenticated API key attached yet.
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("api_keys.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64))
    model_requested: Mapped[str] = mapped_column(String(128))
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    cache_status: Mapped[str] = mapped_column(String(32), default="MISS")
    http_status: Mapped[int] = mapped_column(Integer)
    is_stream: Mapped[bool] = mapped_column(Boolean, default=False)
    total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_requests_tenant_created", "tenant_id", "created_at"),)
