"""PricingRepository against a real in-memory SQLite database (see
tests/conftest.py::sqlite_database)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from llmops_gateway.persistence.models.model_pricing import ModelPricingModel
from llmops_gateway.persistence.repositories.pricing_repository import PricingRepository


async def _seed_pricing(sqlite_database, **overrides) -> None:
    defaults = {
        "provider": "openai",
        "model_name": "gpt-4o",
        "input_price_per_1k": Decimal("0.0025"),
        "output_price_per_1k": Decimal("0.01"),
        "effective_from": datetime.now(UTC) - timedelta(days=1),
    }
    defaults.update(overrides)
    async with sqlite_database.session() as session:
        session.add(ModelPricingModel(**defaults))


async def test_returns_none_when_no_pricing_configured(sqlite_database) -> None:
    async with sqlite_database.session() as session:
        repo = PricingRepository(session)
        result = await repo.get_active_price("openai", "gpt-4o", datetime.now(UTC))
    assert result is None


async def test_returns_active_price_within_effective_window(sqlite_database) -> None:
    await _seed_pricing(sqlite_database)

    async with sqlite_database.session() as session:
        repo = PricingRepository(session)
        result = await repo.get_active_price("openai", "gpt-4o", datetime.now(UTC))

    assert result is not None
    assert float(result.input_price_per_1k) == 0.0025
    assert float(result.output_price_per_1k) == 0.01


async def test_ignores_expired_pricing(sqlite_database) -> None:
    now = datetime.now(UTC)
    await _seed_pricing(
        sqlite_database,
        effective_from=now - timedelta(days=30),
        effective_to=now - timedelta(days=1),
    )

    async with sqlite_database.session() as session:
        repo = PricingRepository(session)
        result = await repo.get_active_price("openai", "gpt-4o", now)
    assert result is None


async def test_ignores_not_yet_effective_pricing(sqlite_database) -> None:
    now = datetime.now(UTC)
    await _seed_pricing(sqlite_database, effective_from=now + timedelta(days=1))

    async with sqlite_database.session() as session:
        repo = PricingRepository(session)
        result = await repo.get_active_price("openai", "gpt-4o", now)
    assert result is None


async def test_prefers_most_recently_effective_row_on_overlap(sqlite_database) -> None:
    now = datetime.now(UTC)
    await _seed_pricing(
        sqlite_database,
        effective_from=now - timedelta(days=100),
        input_price_per_1k=Decimal("0.005"),
    )
    await _seed_pricing(
        sqlite_database,
        effective_from=now - timedelta(days=1),
        input_price_per_1k=Decimal("0.0025"),
    )

    async with sqlite_database.session() as session:
        repo = PricingRepository(session)
        result = await repo.get_active_price("openai", "gpt-4o", now)

    assert result is not None
    assert float(result.input_price_per_1k) == 0.0025


async def test_distinguishes_provider_and_model(sqlite_database) -> None:
    await _seed_pricing(sqlite_database)

    async with sqlite_database.session() as session:
        repo = PricingRepository(session)
        wrong_provider = await repo.get_active_price("anthropic", "gpt-4o", datetime.now(UTC))
        wrong_model = await repo.get_active_price("openai", "gpt-4o-mini", datetime.now(UTC))

    assert wrong_provider is None
    assert wrong_model is None
