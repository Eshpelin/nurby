"""add cameras.enabled (master per-camera enable/disable toggle)

Revision ID: c2e4f6a8b0d1
Revises: e3f5a7c9b1d4
Create Date: 2026-06-18 00:00:00.000000

Adds a master ``enabled`` boolean to the cameras table so an operator
can halt all ingestion, audio, and perception workers for a camera while
keeping its config and history intact. Existing rows back-fill to True
(server_default) so the migration is a no-op for running deployments.

Source: Frigate PRs #16894 (dynamic enable/disable) and #16920 (disabled
camera output suppression). See Nurby issue #88.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c2e4f6a8b0d1"
down_revision: Union[str, Sequence[str], None] = "e3f5a7c9b1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "enabled")
