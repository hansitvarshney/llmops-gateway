"""Seed a default tenant (so requests can be logged before real
multi-tenant auth exists — see `GatewayService.DEFAULT_TENANT_ID`) and
illustrative pricing rows for the models in the default cross-provider
fallback map (`Settings.provider_model_fallback_map`).

Pricing figures are directionally accurate at time of writing but WILL
drift — treat this as seed/example data, not a source of truth. Update via
the `model_pricing` table (versioned by `effective_from`/`effective_to`)
when providers change their rates; never edit historical rows in place.

Revision ID: 0002_seed_defaults
Revises: 0001_initial_schema
Create Date: 2026-07-09

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0002_seed_defaults"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed, well-known UUID so application code (GatewayService.DEFAULT_TENANT_ID)
# can reference this row without a lookup, until real tenant provisioning exists.
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

EFFECTIVE_FROM = datetime(2024, 1, 1, tzinfo=UTC)

# (provider, model_name, input_price_per_1k_usd, output_price_per_1k_usd)
SEED_PRICING = [
    ("openai", "gpt-4o", "0.0025", "0.01"),
    ("openai", "gpt-4o-mini", "0.00015", "0.0006"),
    ("anthropic", "claude-3-5-sonnet-20241022", "0.003", "0.015"),
    ("anthropic", "claude-3-5-haiku-20241022", "0.0008", "0.004"),
]


def upgrade() -> None:
    tenants = sa.table(
        "tenants",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("status", sa.String()),
    )
    op.execute(
        tenants.insert().values(
            id=DEFAULT_TENANT_ID, name="Default Tenant", slug="default", status="active"
        )
    )

    model_pricing = sa.table(
        "model_pricing",
        sa.column("id", sa.Uuid()),
        sa.column("provider", sa.String()),
        sa.column("model_name", sa.String()),
        sa.column("input_price_per_1k", sa.Numeric(12, 6)),
        sa.column("output_price_per_1k", sa.Numeric(12, 6)),
        sa.column("currency", sa.String()),
        sa.column("effective_from", sa.DateTime(timezone=True)),
    )
    op.execute(
        model_pricing.insert().values(
            [
                {
                    "id": uuid.uuid4(),
                    "provider": provider,
                    "model_name": model_name,
                    "input_price_per_1k": input_price,
                    "output_price_per_1k": output_price,
                    "currency": "USD",
                    "effective_from": EFFECTIVE_FROM,
                }
                for provider, model_name, input_price, output_price in SEED_PRICING
            ]
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM model_pricing WHERE provider IN ('openai', 'anthropic')")
    )
    op.execute(sa.text("DELETE FROM tenants WHERE id = :id").bindparams(id=str(DEFAULT_TENANT_ID)))
