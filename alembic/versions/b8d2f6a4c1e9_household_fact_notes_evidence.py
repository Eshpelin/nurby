"""household facts: entity attachment, schedules, suppression, provenance

Issue #185. Extends household_facts with the capture/review/use loop:
what a fact is attached to (entity_kind/entity_key), an optional recurring
schedule, explicitly-confirmed alert suppression with hit accounting,
who wrote and last edited the row, lifecycle transition timestamps, and
the evidence references behind agent-derived facts.

All columns are nullable or defaulted so existing rows carry over as
household-level notes.

Revision ID: b8d2f6a4c1e9
Revises: d3f6a8c1e5b7
Create Date: 2026-09-25 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID


revision: str = 'b8d2f6a4c1e9'
down_revision: Union[str, None] = 'd3f6a8c1e5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "household_facts",
        sa.Column("entity_kind", sa.String(16), nullable=True),
    )
    op.add_column(
        "household_facts",
        sa.Column("entity_key", sa.String(255), nullable=True),
    )
    op.add_column("household_facts", sa.Column("schedule_days", JSON, nullable=True))
    op.add_column(
        "household_facts", sa.Column("schedule_start_minute", sa.Integer(), nullable=True)
    )
    op.add_column(
        "household_facts", sa.Column("schedule_end_minute", sa.Integer(), nullable=True)
    )
    op.add_column("household_facts", sa.Column("schedule_tz", sa.String(64), nullable=True))
    op.add_column(
        "household_facts",
        sa.Column("suppresses_alerts", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "household_facts",
        sa.Column("suppression_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "household_facts",
        sa.Column(
            "suppression_confirmed_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "household_facts",
        sa.Column("suppression_hit_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "household_facts",
        sa.Column("last_suppressed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "household_facts",
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "household_facts",
        sa.Column(
            "updated_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "household_facts", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("household_facts", sa.Column("created_via", sa.String(32), nullable=True))
    op.add_column(
        "household_facts",
        sa.Column("established_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "household_facts", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("household_facts", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("household_facts", sa.Column("evidence_refs", JSON, nullable=True))

    # Existing rows are household-level knowledge; say so explicitly so the
    # API and UI can rely on the field once set.
    op.execute("UPDATE household_facts SET entity_kind = 'household' WHERE entity_kind IS NULL")

    op.create_index(
        "ix_household_facts_entity",
        "household_facts",
        ["entity_kind", "entity_key"],
    )
    # Suppression checks run on the rule-engine tick; keep that lookup to
    # the small armed subset.
    op.create_index(
        "ix_household_facts_suppression",
        "household_facts",
        ["suppresses_alerts", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_household_facts_suppression", table_name="household_facts")
    op.drop_index("ix_household_facts_entity", table_name="household_facts")
    op.drop_column("household_facts", "evidence_refs")
    op.drop_column("household_facts", "rejection_reason")
    op.drop_column("household_facts", "rejected_at")
    op.drop_column("household_facts", "established_at")
    op.drop_column("household_facts", "created_via")
    op.drop_column("household_facts", "updated_at")
    op.drop_column("household_facts", "updated_by_user_id")
    op.drop_column("household_facts", "created_by_user_id")
    op.drop_column("household_facts", "last_suppressed_at")
    op.drop_column("household_facts", "suppression_hit_count")
    op.drop_column("household_facts", "suppression_confirmed_by_user_id")
    op.drop_column("household_facts", "suppression_confirmed_at")
    op.drop_column("household_facts", "suppresses_alerts")
    op.drop_column("household_facts", "schedule_tz")
    op.drop_column("household_facts", "schedule_end_minute")
    op.drop_column("household_facts", "schedule_start_minute")
    op.drop_column("household_facts", "schedule_days")
