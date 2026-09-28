"""Add resident-aware package pickup policy."""

import sqlalchemy as sa
from alembic import op


revision = "fe5f7b9c1d3"
down_revision = "fd4e6a8b0c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "package_pickup_policy",
            sa.String(length=32),
            nullable=False,
            server_default="recognized_person",
        ),
    )
    op.alter_column("cameras", "package_pickup_policy", server_default=None)


def downgrade() -> None:
    op.drop_column("cameras", "package_pickup_policy")
