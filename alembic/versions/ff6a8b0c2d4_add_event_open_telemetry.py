"""Add first-open telemetry for alert detail views (#199)."""

import sqlalchemy as sa
from alembic import op


revision = "ff6a8b0c2d4"
down_revision = "fe5f7b9c1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "opened_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("events", sa.Column("opened_via", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "opened_via")
    op.drop_column("events", "opened_by_user_id")
    op.drop_column("events", "opened_at")
