"""durable distilled household facts

Revision ID: e1a7c4b9d6f2
Revises: d9f4a2c6e8b3
Create Date: 2026-08-24 20:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e1a7c4b9d6f2'
down_revision: Union[str, None] = 'd9f4a2c6e8b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "household_facts",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="habit"),
        sa.Column("source", sa.String(16), nullable=False, server_default="agent"),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("subject_key", "kind", "source", name="uq_household_fact"),
    )
    op.create_index(
        "ix_household_facts_status", "household_facts", ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_household_facts_status", table_name="household_facts")
    op.drop_table("household_facts")
