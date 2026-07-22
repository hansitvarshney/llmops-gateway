"""Add adapter_routes for AdaptLoop LoRA promotion.

Revision ID: 0004_adapter_routes
Revises: 0003_seed_dev_api_key
Create Date: 2026-07-22

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_adapter_routes"
down_revision: str | None = "0003_seed_dev_api_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adapter_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_alias", sa.String(length=128), nullable=False),
        sa.Column("base_model", sa.String(length=128), nullable=False),
        sa.Column("adapter_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "model_alias",
            "stage",
            name="uq_adapter_routes_tenant_alias_stage",
        ),
    )
    op.create_index("ix_adapter_routes_tenant_id", "adapter_routes", ["tenant_id"])
    op.create_index(
        "ix_adapter_routes_tenant_alias_enabled",
        "adapter_routes",
        ["tenant_id", "model_alias", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_adapter_routes_tenant_alias_enabled", table_name="adapter_routes")
    op.drop_index("ix_adapter_routes_tenant_id", table_name="adapter_routes")
    op.drop_table("adapter_routes")
