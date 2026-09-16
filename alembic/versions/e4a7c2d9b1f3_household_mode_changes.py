"""household mode history (#184)

Revision ID: e4a7c2d9b1f3
Revises: d3b9c1e5f7a2
Create Date: 2026-09-15 12:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e4a7c2d9b1f3'
down_revision: Union[str, None] = 'd3b9c1e5f7a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "household_mode_changes",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("previous_mode", sa.String(16), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column(
            "changed_by_user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_household_mode_changes_changed_at",
        "household_mode_changes",
        ["changed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_household_mode_changes_changed_at", table_name="household_mode_changes")
    op.drop_table("household_mode_changes")
