"""Structured alert feedback: useful / correct-but-not-useful / incorrect (#195)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7a9b1d3e5f2"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # useful | correct_but_not_useful | incorrect
        sa.Column("rating", sa.String(24), nullable=False),
        # wrong_object | wrong_person | duplicate | timing — only for incorrect
        sa.Column("reason", sa.String(24), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_feedback_event_user"),
    )
    op.create_index("ix_event_feedback_event_id", "event_feedback", ["event_id"])
    op.create_index("ix_event_feedback_user_id", "event_feedback", ["user_id"])


def downgrade() -> None:
    op.drop_table("event_feedback")
