"""Data-access layer for `token_usage`."""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.domain.entities.chat_response import TokenUsage
from llmops_gateway.persistence.models.token_usage import TokenUsageModel


class TokenUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        request_id: uuid.UUID,
        usage: TokenUsage,
        cost_usd: float,
        pricing_id: uuid.UUID | None = None,
    ) -> TokenUsageModel:
        record = TokenUsageModel(
            request_id=request_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=Decimal(str(cost_usd)),
            pricing_id=pricing_id,
        )
        self._session.add(record)
        await self._session.flush()
        return record
