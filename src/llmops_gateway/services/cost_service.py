"""Token counting + cost calculation against the versioned pricing table.

Pricing is loaded from Postgres `model_pricing` (versioned by
`effective_from`/`effective_to`) rather than hard-coded, so a provider price
change is a data update, not a deploy. Because this lookup sits on the
request path for every cache-miss response, results are cached in Redis
with a short TTL — pricing changes rarely, so a Postgres round-trip on
every single request would be pure waste. A cache miss (including "no
pricing configured for this model") fails soft to a cost of 0.0 rather than
raising, since a missing price row must never break the response path.
"""

from contextlib import suppress
from datetime import UTC, datetime

import structlog
from redis.exceptions import RedisError

from llmops_gateway.domain.entities.chat_response import TokenUsage
from llmops_gateway.domain.value_objects.model_identifier import ModelIdentifier
from llmops_gateway.persistence.database import Database
from llmops_gateway.persistence.repositories.pricing_repository import PricingRepository

logger = structlog.get_logger(__name__)

DEFAULT_PRICING_CACHE_TTL_SECONDS = 300.0
_NO_PRICE_SENTINEL = "NONE"


class CostService:
    def __init__(
        self,
        database: Database,
        redis_client,
        pricing_cache_ttl_seconds: float = DEFAULT_PRICING_CACHE_TTL_SECONDS,
    ) -> None:
        self._database = database
        self._redis = redis_client
        self._pricing_cache_ttl_seconds = pricing_cache_ttl_seconds

    async def calculate_cost_usd(self, model: ModelIdentifier, usage: TokenUsage) -> float:
        pricing = await self._get_pricing(model)
        if pricing is None:
            return 0.0
        input_price_per_1k, output_price_per_1k = pricing
        return (
            usage.input_tokens / 1000 * input_price_per_1k
            + usage.output_tokens / 1000 * output_price_per_1k
        )

    async def _get_pricing(self, model: ModelIdentifier) -> tuple[float, float] | None:
        cache_key = f"pricing:{model}"

        cached = None
        with suppress(RedisError):
            cached = await self._redis.get(cache_key)
        if cached is not None:
            return None if cached == _NO_PRICE_SENTINEL else _decode_pricing(cached)

        pricing = await self._load_from_database(model)

        cache_value = _NO_PRICE_SENTINEL if pricing is None else _encode_pricing(pricing)
        with suppress(RedisError):
            await self._redis.set(cache_key, cache_value, ex=int(self._pricing_cache_ttl_seconds))

        return pricing

    async def _load_from_database(self, model: ModelIdentifier) -> tuple[float, float] | None:
        try:
            async with self._database.session() as session:
                repository = PricingRepository(session)
                record = await repository.get_active_price(
                    model.provider, model.model, datetime.now(UTC)
                )
        except Exception as exc:  # noqa: BLE001 - a DB outage must not break cost calc
            logger.warning("pricing_lookup_failed", model=str(model), error=str(exc))
            return None

        if record is None:
            logger.debug("pricing_not_configured", model=str(model))
            return None
        return float(record.input_price_per_1k), float(record.output_price_per_1k)


def _encode_pricing(pricing: tuple[float, float]) -> str:
    return f"{pricing[0]},{pricing[1]}"


def _decode_pricing(raw: str) -> tuple[float, float] | None:
    input_str, _, output_str = raw.partition(",")
    try:
        return float(input_str), float(output_str)
    except ValueError:
        return None
