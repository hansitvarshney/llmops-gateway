"""Add canary_percent to adapter_routes for % Staging traffic split.

Revision ID: 0005_adapter_canary_percent
Revises: 0004_adapter_routes
Create Date: 2026-07-22

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_adapter_canary_percent"
down_revision: str | None = "0004_adapter_routes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "adapter_routes",
        sa.Column("canary_percent", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("adapter_routes", "canary_percent")
