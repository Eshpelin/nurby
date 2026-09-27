"""Record whether observation VLM usage came from provider counters."""

import sqlalchemy as sa
from alembic import op

revision = "fa1b2c3d4e5f"
# The privacy-control and explicit-camera-access lines were previously
# developed in parallel. This migration is the first shared descendant and
# intentionally reconciles both heads before adding the usage column.
down_revision = ("f4f3a7c9e1d2", "f9c2d4e6a8b0")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "observation_vlm_passes",
        sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("observation_vlm_passes", "estimated")
