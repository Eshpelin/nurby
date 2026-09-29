"""Add first clip-play telemetry for retained monitoring (#199)."""

import sqlalchemy as sa
from alembic import op


revision = "ff7b9c1d3e5"
down_revision = "ff6a8b0c2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("clip_opened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "clip_opened_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("events", sa.Column("clip_opened_via", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "clip_opened_via")
    op.drop_column("events", "clip_opened_by_user_id")
    op.drop_column("events", "clip_opened_at")
