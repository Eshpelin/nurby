"""scheduled_reports table

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-06-11 00:00:00.000000

Saved, recurring agent questions with a delivery schedule ("what was
Simon doing all day, every night at 7 PM"). See shared/models.py
ScheduledReport and services/api/report_scheduler.py.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "person_id", UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("hour", sa.Integer(), nullable=False, server_default="19"),
        sa.Column("minute", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("days", JSON(), nullable=True),
        sa.Column("delivery", JSON(), nullable=True),
        sa.Column(
            "provider_id", UUID(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_output", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduled_reports")
