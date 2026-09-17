"""Distinguish inferred pickup from confirmed handover (#191).

Adds ``guardian_events.handover_state`` (the evidence state of a pickup) and the
append-only ``guardian_handover_confirmations`` audit table that records who
confirmed or corrected a handover, when, and on what evidence.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1c3e5b7d9f2"
down_revision = "c7a9b1d3e5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guardian_events",
        sa.Column("handover_state", sa.String(16), nullable=True),
    )
    op.create_table(
        "guardian_handover_confirmations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("guardian_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # confirmed | corrected
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("prior_state", sa.String(16), nullable=True),
        sa.Column(
            "confirmed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence", postgresql.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_guardian_handover_confirmations_event_id",
        "guardian_handover_confirmations",
        ["event_id"],
    )
    op.create_index(
        "ix_guardian_handover_confirmations_person_id",
        "guardian_handover_confirmations",
        ["person_id"],
    )
    op.create_index(
        "ix_guardian_handover_confirmations_confirmed_by_user_id",
        "guardian_handover_confirmations",
        ["confirmed_by_user_id"],
    )
    op.create_index(
        "ix_guardian_handover_confirmations_at",
        "guardian_handover_confirmations",
        ["at"],
    )


def downgrade() -> None:
    op.drop_table("guardian_handover_confirmations")
    op.drop_column("guardian_events", "handover_state")
