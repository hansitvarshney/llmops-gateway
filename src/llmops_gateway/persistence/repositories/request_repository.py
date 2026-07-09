"""Data-access layer for `requests`.

Kept as a thin repository over the ORM model so services depend on
intention-revealing methods rather than raw SQLAlchemy queries scattered
throughout the codebase.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.persistence.models.request_log import RequestLogModel


class RequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **fields) -> RequestLogModel:
        """Inserts a request row and flushes so `.id` is populated —
        without committing — leaving the caller (TracingService) in
        control of the transaction boundary so spans/token-usage rows can
        be written in the same unit of work."""
        record = RequestLogModel(**fields)
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_trace_id(self, trace_id: str) -> RequestLogModel | None:
        stmt = select(RequestLogModel).where(RequestLogModel.trace_id == trace_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
