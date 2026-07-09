import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ApiKeyModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "api_keys"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("tenants.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    # JSON rather than Postgres ARRAY so this model stays portable to SQLite
    # for tests; on Postgres this still stores/queries fine as a JSON array.
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
