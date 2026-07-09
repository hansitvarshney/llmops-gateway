"""CostService against a real in-memory SQLite database (pricing lookups)
and fakeredis (the pricing cache layer)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis

from llmops_gateway.domain.entities.chat_response import TokenUsage
from llmops_gateway.domain.value_objects.model_identifier import ModelIdentifier
from llmops_gateway.persistence.models.model_pricing import ModelPricingModel
from llmops_gateway.services.cost_service import CostService


async def _seed_pricing(sqlite_database) -> None:
    async with sqlite_database.session() as session:
        session.add(
            ModelPricingModel(
                provider="openai",
                model_name="gpt-4o",
                input_price_per_1k=Decimal("0.0025"),
                output_price_per_1k=Decimal("0.01"),
                effective_from=datetime.now(UTC) - timedelta(days=1),
            )
        )


def _redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


async def test_calculates_cost_from_configured_pricing(sqlite_database) -> None:
    await _seed_pricing(sqlite_database)
    service = CostService(sqlite_database, _redis())

    cost = await service.calculate_cost_usd(
        ModelIdentifier(provider="openai", model="gpt-4o"),
        TokenUsage(input_tokens=1000, output_tokens=1000),
    )

    assert cost == 0.0025 + 0.01  # 1000 tokens = exactly 1x the per-1k rate


async def test_returns_zero_when_no_pricing_configured(sqlite_database) -> None:
    service = CostService(sqlite_database, _redis())

    cost = await service.calculate_cost_usd(
        ModelIdentifier(provider="openai", model="unknown-model"),
        TokenUsage(input_tokens=1000, output_tokens=1000),
    )

    assert cost == 0.0


async def test_second_lookup_is_served_from_cache_not_the_database(sqlite_database) -> None:
    await _seed_pricing(sqlite_database)
    redis_client = _redis()
    service = CostService(sqlite_database, redis_client)
    model = ModelIdentifier(provider="openai", model="gpt-4o")

    first = await service.calculate_cost_usd(model, TokenUsage(input_tokens=1000, output_tokens=0))
    assert first == 0.0025

    # Wipe the underlying table entirely — if the second call still returns
    # the correct price, it can only have come from the Redis cache.
    async with sqlite_database.session() as session:
        from sqlalchemy import delete

        await session.execute(delete(ModelPricingModel))

    second = await service.calculate_cost_usd(model, TokenUsage(input_tokens=1000, output_tokens=0))
    assert second == first


async def test_negative_lookup_is_also_cached(sqlite_database) -> None:
    redis_client = _redis()
    service = CostService(sqlite_database, redis_client)
    model = ModelIdentifier(provider="openai", model="never-configured")

    await service.calculate_cost_usd(model, TokenUsage(input_tokens=1, output_tokens=1))
    cached_value = await redis_client.get(f"pricing:{model}")
    assert cached_value == "NONE"


async def test_redis_outage_falls_back_to_database_without_raising(sqlite_database) -> None:
    await _seed_pricing(sqlite_database)

    from redis.exceptions import RedisError

    class _BrokenRedis:
        async def get(self, key):
            raise RedisError("redis is down")

        async def set(self, *args, **kwargs):
            raise RedisError("redis is down")

    service = CostService(sqlite_database, _BrokenRedis())

    cost = await service.calculate_cost_usd(
        ModelIdentifier(provider="openai", model="gpt-4o"),
        TokenUsage(input_tokens=1000, output_tokens=1000),
    )
    assert cost == 0.0025 + 0.01  # still correct — just served straight from Postgres
