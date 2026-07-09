import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from llmops_gateway.persistence.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class CacheEntryMetaModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Relational mirror of Qdrant semantic-cache points, used for analytics
    and the scheduled GC/eviction job (LRU/LFU on hit_count + last_hit_at)."""

    __tablename__ = "cache_entries_meta"

    qdrant_point_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("requests.id"), nullable=True
    )
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(128))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ttl_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
