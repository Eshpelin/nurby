"""Expected-activity expectations for absence alerts (#215).

Stores the scheduled windows the sweeper evaluates: an expected subject
(named person / any person / any activity), place, weekday + time window,
grace, household-mode scoping, and the last evaluation outcome for dedupe +
recap.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision = "b5d7f9a1c3e5"
down_revision = "a3c5e7f9b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expected_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subject_kind", sa.String(length=16), nullable=False, server_default="person"),
        sa.Column("subject_key", sa.String(length=255), nullable=True),
        sa.Column("camera_ids", JSON(), nullable=True),
        sa.Column("weekdays", JSON(), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("active_modes", JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_evaluated_on", sa.String(length=10), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_expected_activities_enabled", "expected_activities", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_expected_activities_enabled", table_name="expected_activities")
    op.drop_table("expected_activities")
