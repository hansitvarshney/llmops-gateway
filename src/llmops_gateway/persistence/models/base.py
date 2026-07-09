"""Declarative base + common column mixins shared by every ORM model.

Uses SQLAlchemy's cross-dialect `Uuid`/`JSON` types (native on Postgres,
transparently emulated elsewhere) rather than `sqlalchemy.dialects.postgresql`
types, so the exact same models can run against SQLite for fast repository
tests without a Postgres/Docker dependency, while still using Postgres's
native UUID/JSONB storage in production.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
