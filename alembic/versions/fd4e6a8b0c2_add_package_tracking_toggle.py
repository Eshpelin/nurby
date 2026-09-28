"""Add per-camera package lifecycle subscription."""

import sqlalchemy as sa
from alembic import op


revision = "fd4e6a8b0c2"
down_revision = "fc3d5e7f9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("package_tracking_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("cameras", "package_tracking_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("cameras", "package_tracking_enabled")
