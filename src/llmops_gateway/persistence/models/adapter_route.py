"""Tenant-scoped model alias → base_model + adapter_id routing for AdaptLoop."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AdapterRouteModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Maps a client-facing model alias to an upstream base model + LoRA adapter.

    Looked up on the request path before cache/routing so AdaptLoop-promoted
    adapters can be selected without changing client SDK model strings.

    ``canary_percent`` on a Staging row controls what fraction of alias traffic
    is steered to that Staging adapter (remainder uses Production when present).
    """

    __tablename__ = "adapter_routes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_alias",
            "stage",
            name="uq_adapter_routes_tenant_alias_stage",
        ),
        Index("ix_adapter_routes_tenant_alias_enabled", "tenant_id", "model_alias", "enabled"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("tenants.id"), nullable=False, index=True
    )
    model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    base_model: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="Production")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
