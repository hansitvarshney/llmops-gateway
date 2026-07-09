"""Seed a development API key for the default tenant.

The plaintext key is intentionally NOT stored — only its hash. Use this
credential locally after `make migrate`:

  X-API-Key: llmops_dev_default_key

Hash is computed with the default `auth_api_key_pepper`
(`dev-insecure-pepper-change-me`). If you change the pepper in production,
existing keys must be re-hashed or re-issued.

Revision ID: 0003_seed_dev_api_key
Revises: 0002_seed_defaults
Create Date: 2026-07-09

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_seed_dev_api_key"
down_revision: str | None = "0002_seed_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_KEY_HASH = "827cce41dfd3ad5b8042748ea51ae2dc2b5d2f7577eaf1fa912cac65c3d50a61"


def upgrade() -> None:
    api_keys = sa.table(
        "api_keys",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("key_hash", sa.String()),
        sa.column("name", sa.String()),
        sa.column("scopes", sa.JSON()),
    )
    op.execute(
        api_keys.insert().values(
            id=uuid.uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            key_hash=DEV_KEY_HASH,
            name="Development default key",
            scopes=["*"],
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM api_keys WHERE key_hash = :hash").bindparams(hash=DEV_KEY_HASH)
    )
