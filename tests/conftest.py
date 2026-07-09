"""Shared pytest fixtures.

`sqlite_database` gives repository/service tests a real (in-memory SQLite)
`Database` instance rather than a mock — consistent with this project's
"test against a genuine lightweight backend" philosophy already used for
Qdrant (`:memory:` mode) and Redis (`fakeredis`) in earlier phases. This
only works because `persistence/models/` deliberately uses cross-dialect
`Uuid`/`JSON` column types instead of Postgres-only ones.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from llmops_gateway.persistence.database import Database
from llmops_gateway.persistence.models import Base


class _SQLiteDatabase(Database):
    """Same `Database` interface consumed directly by CostService and
    TracingService, backed by an in-memory SQLite engine instead of the
    Postgres one `Database.__init__` normally builds from Settings."""

    def __init__(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)


@pytest.fixture
async def sqlite_database():
    database = _SQLiteDatabase()
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield database
    finally:
        await database.dispose()
