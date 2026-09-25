"""add immutable association review audit events

Revision ID: f3d1a5c7e9b2
Revises: f3c9e1a5b7d0
Create Date: 2026-09-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f3d1a5c7e9b2"
down_revision: Union[str, None] = "f3c9e1a5b7d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "association_review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("association_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entity_associations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("old_status", sa.String(16), nullable=False),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_association_review_events_association_id", "association_review_events", ["association_id"])
    op.create_index("ix_association_review_events_reviewer_user_id", "association_review_events", ["reviewer_user_id"])


def downgrade() -> None:
    op.drop_index("ix_association_review_events_reviewer_user_id", table_name="association_review_events")
    op.drop_index("ix_association_review_events_association_id", table_name="association_review_events")
    op.drop_table("association_review_events")
